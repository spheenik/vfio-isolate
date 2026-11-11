"""Scenario tests for the hugepages command (openspec/changes/hugepages/specs/hugepages/spec.md)."""
import pytest

from vfio_isolate import hugepages, journal
from vfio_isolate.cli import main

M2 = 2048
G1 = 1048576


def run(*argv):
    return main(list(argv))


def test_add_pages(fake_host, tmp_path):
    fake_host.set_hugepages(M2, 4)
    assert run("-u", str(tmp_path / "j"), "hugepages", "2M", "16M") == 0
    assert fake_host.hugepages(M2) == 12


def test_add_on_node(fake_host, tmp_path):
    assert run("-u", str(tmp_path / "j"), "hugepages", "--node", "N0", "1G", "2G") == 0
    assert fake_host.hugepages(G1, 0) == 2
    assert fake_host.hugepages(G1) == 0


def test_undo_releases_what_was_added(fake_host, tmp_path):
    j = str(tmp_path / "j")
    fake_host.set_hugepages(M2, 4)
    assert run("-u", j, "hugepages", "2M", "16M") == 0
    fake_host.set_hugepages(M2, 16)
    assert run("restore", j) == 0
    assert fake_host.hugepages(M2) == 8


@pytest.mark.parametrize("order", ["ab", "ba"])
def test_overlapping_runs_restore_in_any_order(fake_host, tmp_path, order):
    files = {"a": str(tmp_path / "a"), "b": str(tmp_path / "b")}
    assert run("-u", files["a"], "hugepages", "2M", "16M") == 0
    assert run("-u", files["b"], "hugepages", "2M", "16M") == 0
    assert fake_host.hugepages(M2) == 16
    for k in order:
        assert run("restore", files[k]) == 0
    assert fake_host.hugepages(M2) == 0


def test_release_never_goes_below_zero(fake_host, tmp_path):
    j = str(tmp_path / "j")
    assert run("-u", j, "hugepages", "2M", "16M") == 0
    fake_host.set_hugepages(M2, 3)
    assert run("restore", j) == 0
    assert fake_host.hugepages(M2) == 0


def test_release_with_pages_in_use_succeeds(fake_host, tmp_path):
    j = str(tmp_path / "j")
    assert run("-u", j, "hugepages", "2M", "16M") == 0
    fake_host.set_hugepages(M2, 8, in_use=5)
    assert run("restore", j) == 0
    assert fake_host.hugepages(M2) == 5


def test_shortfall_rolls_back_and_leaves_no_record(fake_host, tmp_path, capsys):
    j = str(tmp_path / "j")
    fake_host.set_hugepages(G1, 0, capacity=2)
    assert run("-u", j, "hugepages", "1G", "6G") == 1
    err = capsys.readouterr().err
    assert err.strip() == ("vfio-isolate: hugepages failed: got 2G of 6G in 1G pages; "
                           "the pages were released; nothing was changed")
    assert fake_host.hugepages(G1) == 0
    assert journal.read_journal(j) == []


def test_shortfall_message_names_node(fake_host, tmp_path, capsys):
    fake_host.set_hugepages(G1, 0, node=0, capacity=2)
    assert run("-u", str(tmp_path / "j"), "hugepages", "--node", "N0", "1G", "6G") == 1
    assert "got 2G of 6G in 1G pages on node N0; the pages were released" in capsys.readouterr().err


def test_restore_after_shortfall_keeps_static_pool(fake_host, tmp_path):
    j = str(tmp_path / "j")
    fake_host.set_hugepages(G1, 4, capacity=6)
    assert run("-u", j, "hugepages", "1G", "6G") == 1
    assert fake_host.hugepages(G1) == 4
    assert run("restore", j) == 0
    assert fake_host.hugepages(G1) == 4


def test_shortfall_after_earlier_change_keeps_it_restorable(fake_host, tmp_path, capsys):
    j = str(tmp_path / "j")
    fake_host.set_hugepages(G1, 0, capacity=2)
    assert run("-u", j, "hugepages", "2M", "16M", "hugepages", "1G", "6G") == 1
    assert 'restore' in capsys.readouterr().err
    assert fake_host.hugepages(M2) == 8
    assert run("restore", j) == 0
    assert fake_host.hugepages(M2) == 0


def test_unsupported_size_is_usage_error(fake_host, tmp_path, capsys):
    j = str(tmp_path / "j")
    assert run("-u", j, "hugepages", "4M", "8M") == 2
    err = capsys.readouterr().err
    assert "'4M' is not an available page size; available: 2M 1G" in err
    assert fake_host.hugepages(M2) == 0


@pytest.mark.parametrize("text,kb", [("2M", M2), ("2048k", M2), ("2048KB", M2), ("1g", G1),
                                     ("2m", M2), ("1GB", G1)])
def test_size_forms(fake_host, tmp_path, text, kb):
    assert run("-u", str(tmp_path / "j"), "hugepages", text, "6G") == 0
    assert fake_host.hugepages(kb) == 6 * G1 // kb
    other = G1 if kb == M2 else M2
    assert fake_host.hugepages(other) == 0


def test_garbage_size_rejected(fake_host, tmp_path, capsys):
    assert run("-u", str(tmp_path / "j"), "hugepages", "lots", "3M") == 2
    assert "not a size" in capsys.readouterr().err


def test_missing_node_rejected(fake_host, tmp_path, capsys):
    assert run("-u", str(tmp_path / "j"), "hugepages", "--node", "N1", "2M", "6M") == 2
    assert "NUMA nodes 1 do not exist" in capsys.readouterr().err


def test_node_without_pool_lists_nodes(fake_host, tmp_path, capsys):
    fake_host._write("sys/devices/system/node/online", "0-1\n")
    fake_host._write("sys/devices/system/node/possible", "0-1\n")
    fake_host._write("sys/devices/system/node/node1/cpulist", "1\n")
    assert run("-u", str(tmp_path / "j"), "hugepages", "--node", "N1", "2M", "6M") == 2
    err = capsys.readouterr().err
    assert "NUMA node N1 has no 2M hugepage pool" in err
    assert "nodes with one: N0" in err


@pytest.mark.parametrize("amount", ["0", "0M", "-1", "x", "1.5G"])
def test_bad_amount_rejected(fake_host, tmp_path, amount):
    assert run("-u", str(tmp_path / "j"), "hugepages", "2M", "--", amount) == 2
    assert fake_host.hugepages(M2) == 0


@pytest.mark.parametrize("size,amount,msg", [("2M", "3M", "3M is not a multiple of 2M"),
                                             ("1G", "1536M", "1536M is not a multiple of 1G")])
def test_amount_must_be_multiple(fake_host, tmp_path, capsys, size, amount, msg):
    assert run("-u", str(tmp_path / "j"), "hugepages", size, amount) == 2
    assert msg in capsys.readouterr().err


def test_swapped_arguments_rejected(fake_host, tmp_path, capsys):
    assert run("-u", str(tmp_path / "j"), "hugepages", "16G", "2M") == 2
    assert "'16G' is not an available page size; available: 2M 1G" in capsys.readouterr().err
    assert fake_host.hugepages(M2) == 0


def test_page_size_and_amount_are_mandatory(fake_host, tmp_path):
    assert run("-u", str(tmp_path / "j"), "hugepages", "2M") == 2
    assert run("-u", str(tmp_path / "j"), "hugepages") == 2
    assert run("-u", str(tmp_path / "j"), "hugepages", "--size", "2M", "8") == 2


def test_node_must_be_single(fake_host, tmp_path, capsys):
    fake_host._write("sys/devices/system/node/online", "0-1\n")
    fake_host._write("sys/devices/system/node/possible", "0-1\n")
    fake_host._write("sys/devices/system/node/node1/cpulist", "1\n")
    assert run("-u", str(tmp_path / "j"), "hugepages", "--node", "N0-1", "2M", "6M") == 2
    assert "--node takes exactly one node, e.g. N0" in capsys.readouterr().err


def test_node_needs_n_form(fake_host, tmp_path, capsys):
    assert run("-u", str(tmp_path / "j"), "hugepages", "--node", "0", "2M", "6M") == 2
    assert "written with N, e.g. N0" in capsys.readouterr().err
    assert fake_host.hugepages(M2, 0) == 0


def test_size_helpers():
    assert hugepages.format_size(2048) == "2M"
    assert hugepages.format_size(1048576) == "1G"
    assert hugepages.format_size(64) == "64K"
    assert hugepages.format_size(512 * 1024) == "512M"
    assert hugepages.format_size(4096) == "4M"
    assert hugepages.format_size(1500) == "1500K"
    assert hugepages.parse_size("64k") == 64
    with pytest.raises(ValueError):
        hugepages.parse_size("0M")


def _failing_write(monkeypatch, fail_on, fail_writeback=False):
    """Make the write of `fail_on` pages raise EIO (and optionally the write-back too)."""
    real = hugepages.write_count

    def write_count(size_kb, node, count):
        if count == fail_on or fail_writeback:
            raise OSError(5, "Input/output error")
        real(size_kb, node, count)

    monkeypatch.setattr(hugepages, "write_count", write_count)


def test_write_error_rolls_back_and_leaves_no_record(fake_host, tmp_path, capsys, monkeypatch):
    j = str(tmp_path / "j")
    fake_host.set_hugepages(M2, 4)
    _failing_write(monkeypatch, 12)
    assert run("-u", j, "hugepages", "2M", "16M") == 1
    err = capsys.readouterr().err
    assert ("hugepages failed: could not add 16M in 2M pages: [Errno 5] Input/output error; "
            "nothing was kept") in err
    assert fake_host.hugepages(M2) == 4
    assert journal.read_journal(j) == []


def test_write_error_with_failed_writeback_keeps_record(fake_host, tmp_path, capsys, monkeypatch):
    j = str(tmp_path / "j")
    fake_host.set_hugepages(M2, 4)
    real = hugepages.write_count
    calls = []

    def write_count(size_kb, node, count):
        calls.append(count)
        if len(calls) == 1:
            real(size_kb, node, count)  # the pages are added ...
            raise OSError(5, "Input/output error")  # ... but the call reports an error
        raise OSError(16, "Device or resource busy")  # and the write-back fails too

    monkeypatch.setattr(hugepages, "write_count", write_count)
    assert run("-u", j, "hugepages", "2M", "16M") == 1
    err = capsys.readouterr().err
    assert "Input/output error" in err and "nothing was kept" not in err
    assert fake_host.hugepages(M2) == 12
    assert len(journal.read_journal(j)) == 1
