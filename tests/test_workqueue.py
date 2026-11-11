"""Scenario tests for workqueue-affinity (openspec/changes/kernel-noise/specs/workqueue-affinity)."""
import errno

import pytest

from vfio_isolate import workqueue
from vfio_isolate.cli import main
from vfio_isolate.nodeset import CPUNodeSet


def run(*argv):
    return main(list(argv))


@pytest.fixture
def host(fake_host_factory):
    h = fake_host_factory(num_cpus=32)
    return h


def mask(host, name="cpumask"):
    return host.workqueue_mask(name).to_list_form()


def test_mask_and_restore(host, tmp_path):
    j = str(tmp_path / "j")
    assert run("-u", j, "workqueue-affinity", "mask", "C8-15,24-31") == 0
    assert mask(host) == "0-7,16-23"
    assert run("restore", j) == 0
    assert mask(host) == "0-31"


def test_add(host, tmp_path):
    host.set_workqueue("0-7")
    j = str(tmp_path / "j")
    assert run("-u", j, "workqueue-affinity", "add", "C8-9") == 0
    assert mask(host) == "0-9"
    assert run("restore", j) == 0
    assert mask(host) == "0-7"


def test_nothing_would_remain(host, tmp_path, capsys):
    j = str(tmp_path / "j")
    assert run("-u", j, "workqueue-affinity", "mask", "C0-31") == 1
    assert "no CPU would remain" in capsys.readouterr().err
    assert mask(host) == "0-31"


def test_isolated_refused(host, capsys):
    host.set_workqueue("0-31", isolated="8-15")
    for op in ("add", "mask"):
        assert run("workqueue-affinity", op, "C8-15") == 1
        assert "CPUs 8-15 are in isolated cpuset partitions" in capsys.readouterr().err
        assert mask(host, "cpumask_requested") == "0-31"
        assert mask(host) == "0-7,16-31"


def test_only_offline_cpus_remain_is_refused(host, capsys):
    host.set_workqueue("0-7")
    (host.root / "sys/devices/system/cpu/online").write_text("0-3\n")
    assert run("workqueue-affinity", "mask", "C0-3") == 1
    assert "no CPU would remain" in capsys.readouterr().err
    assert mask(host, "cpumask_requested") == "0-7"


def test_chain_workqueue_then_partition_restores_fully(host, tmp_path):
    host.mkcg("x", cpus=None)
    j = str(tmp_path / "j")
    assert run("-u", j, "workqueue-affinity", "mask", "C2", "cpuset-modify", "--partition", "isolated",
               "--cpus", "C4-7", "/x") == 0
    assert mask(host, "cpumask_requested") == "0-1,3-31"
    assert host.workqueue_effective().to_list_form() == "0-1,3,8-31"
    assert run("restore", j) == 0
    assert mask(host, "cpumask_requested") == "0-31"
    assert host.workqueue_effective().to_list_form() == "0-31"


def test_partition_then_workqueue_is_refused(host, tmp_path, capsys):
    host.mkcg("x", cpus=None)
    j = str(tmp_path / "j")
    assert run("-u", j, "cpuset-modify", "--partition", "isolated", "--cpus", "C4-7", "/x") == 0
    assert run("workqueue-affinity", "mask", "C2") == 1
    assert "CPUs 4-7 are in isolated cpuset partitions" in capsys.readouterr().err
    assert mask(host, "cpumask_requested") == "0-31"


def test_undo_while_partition_active(host, tmp_path):
    j = str(tmp_path / "j")
    assert run("-u", j, "workqueue-affinity", "mask", "C0-3") == 0
    host.set_workqueue("4-31", isolated="8-15")
    assert run("restore", j) == 0
    assert mask(host) == "0-7,16-31"


def test_undo_with_nothing_left_uses_online_non_isolated(host, tmp_path):
    j = str(tmp_path / "j")
    host.set_workqueue("8-15")
    assert run("-u", j, "workqueue-affinity", "add", "C0-1") == 0
    host.set_workqueue("0-31", isolated="8-15")
    # previous mask 8-15 is entirely isolated now
    assert run("restore", j) == 0
    assert mask(host) == "0-7,16-31"


def test_fallback_without_cpumask_requested(host, tmp_path):
    (host.root / "sys/devices/virtual/workqueue/cpumask_requested").unlink()
    (host.root / "sys/devices/virtual/workqueue/cpumask_isolated").unlink()
    host.has_requested = False
    j = str(tmp_path / "j")
    assert run("-u", j, "workqueue-affinity", "mask", "C0-3") == 0
    assert mask(host) == "4-31"
    assert run("restore", j) == 0
    assert mask(host) == "0-31"


@pytest.mark.parametrize("err,text", [
    (errno.EOVERFLOW, "CPUs beyond the highest possible CPU"),
    (errno.EINVAL, "the kernel rejected mask"),
])
def test_errno_mapping(host, monkeypatch, capsys, err, text):
    def boom(cpus):
        raise OSError(err, "x")
    monkeypatch.setattr(workqueue, "write_cpumask", boom)
    assert run("workqueue-affinity", "mask", "C0-3") == 1
    assert text in capsys.readouterr().err


def test_other_errno_is_reported_unmapped(host, monkeypatch, capsys):
    def boom(cpus):
        raise OSError(errno.EACCES, "x")
    monkeypatch.setattr(workqueue, "write_cpumask", boom)
    assert run("workqueue-affinity", "mask", "C0-3") == 1
    err = capsys.readouterr().err
    assert "workqueue-affinity failed" in err and "rejected" not in err


@pytest.mark.parametrize("cpus,text", [
    ("0-3", "0000000f"), ("31", "80000000"), ("32", "00000001,00000000"),
    ("0,32-33", "00000003,00000001"),
])
def test_format_mask(cpus, text):
    assert workqueue.format_mask(CPUNodeSet(cpus)) == text
