"""Scenario tests for the undo journal (openspec/changes/undo-journal/specs/undo-journal/spec.md)."""
import json
import os
import pickle
import shutil
import stat

import pytest

from vfio_isolate import fsroot, journal
from vfio_isolate.cli import main
from vfio_isolate.cpuset import CPUSet

HEADER = json.dumps({"format": "vfio-isolate-undo", "version": 1}) + "\n"


@pytest.fixture
def host(fake_host):
    fake_host.patch_cgroup_fs()
    return fake_host


@pytest.fixture
def j(tmp_path):
    return str(tmp_path / "j")


def gov(host, n):
    return host.read(f"sys/devices/system/cpu/cpu{n}/cpufreq/scaling_governor").strip()


def cpus_of(host, name):
    return (host.root / host.cgroup_mount.lstrip("/") / name.lstrip("/") / "cpuset.cpus").read_text()


def write_journal(path, content, mode=0o600):
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, mode)


def step_names(path):
    return [(s.action.name, s.params) for r in journal.read_journal(path) for s in r]


# ---------------------------------------------------------------- recording

def test_failure_part_way_through_a_chain(host, j):
    host.mkcg("a")
    rc = main(["-u", j, "cpu-governor", "performance", "C0",
               "cpuset-modify", "--cpus", "C0-3", "/a",
               "cpuset-modify", "--cpus", "C0-3", "/missing"])
    assert rc != 0
    assert gov(host, 0) == "performance"
    assert cpus_of(host, "a") == "0-3"
    assert len(journal.read_journal(j)) == 2
    assert main(["restore", j]) == 0
    assert gov(host, 0) == "powersave"
    # the undo captures the configured cpuset.cpus (empty = inherit)
    assert cpus_of(host, "a") == "\n"


def test_cpuset_create_fails_after_undo_recorded(host, j, monkeypatch):
    def boom(self, *a, **k):
        raise OSError("boom")
    with monkeypatch.context() as m:
        m.setattr(CPUSet, "create", boom)
        with pytest.raises(OSError):
            main(["-u", j, "cpuset-create", "/a"])
    assert fsroot.ROOT == str(host.root)
    assert [n for n, _ in step_names(j)] == ["cpuset-delete"]
    assert main(["restore", j]) == 0
    assert not os.path.exists(j)


def test_cpuset_delete_fails_after_undo_recorded(host, j, monkeypatch):
    cg = host.mkcg("a", cpus="2-3", mems="0")
    (cg / "cpuset.cpus").write_text("2-3\n")
    (cg / "cpuset.mems").write_text("0\n")

    def boom(self, *a, **k):
        raise OSError("boom")
    with monkeypatch.context() as m:
        m.setattr(CPUSet, "remove", boom)
        with pytest.raises(OSError):
            main(["-u", j, "cpuset-delete", "/a"])
    assert fsroot.ROOT == str(host.root)
    assert main(["restore", j]) == 0
    assert cpus_of(host, "a") == "2-3"
    assert (host.root / host.cgroup_mount.lstrip("/") / "a" / "cpuset.mems").read_text() == "0"
    assert not os.path.exists(j)


def test_precondition_failure_records_nothing(host, j, capsys):
    host.mkcg("a")
    assert main(["-u", j, "cpuset-create", "/a"]) == 1
    assert "/a" in capsys.readouterr().err
    assert (host.root / host.cgroup_mount.lstrip("/") / "a").is_dir()
    assert journal.read_journal(j) == []


# ---------------------------------------------------------------- order

def test_undo_of_cpuset_delete(host, j):
    cg = host.mkcg("a", cpus="2-3", mems="0")
    (cg / "cpuset.cpus").write_text("2-3\n")
    (cg / "cpuset.mems").write_text("0\n")
    assert main(["-u", j, "cpuset-delete", "/a"]) == 0
    assert not (host.root / host.cgroup_mount.lstrip("/") / "a").exists()
    assert main(["restore", j]) == 0
    assert cpus_of(host, "a") == "2-3"
    assert (host.root / host.cgroup_mount.lstrip("/") / "a" / "cpuset.mems").read_text() == "0"


def test_undo_of_full_irq_mask(host, j):
    host.add_irq(5, "2")
    assert main(["-u", j, "irq-affinity", "mask", "C2-3"]) == 0
    assert host.read("proc/irq/5/smp_affinity_list").strip() != "2"
    assert main(["restore", j]) == 0
    assert host.read("proc/irq/5/smp_affinity_list").strip() == "2"


def test_chain_undone_newest_first(host, j):
    assert main(["-u", j, "cpu-governor", "performance", "C0",
                 "cpu-governor", "schedutil", "C0"]) == 0
    assert gov(host, 0) == "schedutil"
    assert main(["restore", j]) == 0
    assert gov(host, 0) == "powersave"


# ---------------------------------------------------------------- append

def test_prepare_runs_twice(host, j):
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 0
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 0
    assert main(["restore", j]) == 0
    assert gov(host, 0) == "powersave"
    assert not os.path.exists(j)


def test_prepare_retried_after_partial_failure(host, j):
    assert main(["-u", j, "cpu-governor", "performance", "C0",
                 "cpuset-modify", "--cpus", "C0-3", "/missing"]) == 1
    assert gov(host, 0) == "performance"
    assert main(["-u", j, "cpu-governor", "performance", "C0-1"]) == 0
    assert main(["restore", j]) == 0
    assert gov(host, 0) == "powersave" and gov(host, 1) == "powersave"


def test_existing_file_is_not_a_journal(host, j):
    write_journal(j, "hello\n")
    assert main(["-u", j, "drop-caches"]) == 1
    assert host.read("proc/sys/vm/drop_caches") == "0"
    assert open(j).read() == "hello\n"


# ---------------------------------------------------------------- restore failures

def test_one_step_fails(host, j, capsys):
    host.mkcg("a")
    host.mkcg("b")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a",
                 "cpuset-modify", "--cpus", "C0-3", "/b"]) == 0
    shutil.rmtree(host.root / host.cgroup_mount.lstrip("/") / "b")
    capsys.readouterr()
    assert main(["restore", j]) == 1
    err = capsys.readouterr().err
    assert "restore: cpuset-modify" in err and "/b" in err
    assert cpus_of(host, "a") == "\n"
    steps = step_names(j)
    assert len(steps) == 1 and steps[0][1].cpuset_name == "/b"


def test_clean_restore(host, j):
    assert main(["-u", j, "cpu-governor", "performance", "C0-1"]) == 0
    assert main(["restore", j]) == 0
    assert not os.path.exists(j)


def test_missing_journal(host, j, capsys):
    assert main(["restore", j]) == 1
    assert j in capsys.readouterr().err


# ---------------------------------------------------------------- safety

def test_journal_permissions(host, j):
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 0
    assert stat.S_IMODE(os.stat(j).st_mode) == 0o600


def test_symlink_at_journal_path(host, tmp_path):
    target = tmp_path / "target"
    target.write_text("untouched")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert main(["-u", str(link), "cpu-governor", "performance", "C0"]) == 1
    assert target.read_text() == "untouched"
    assert gov(host, 0) == "powersave"
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "nowhere")
    assert main(["-u", str(dangling), "cpu-governor", "performance", "C0"]) == 1
    assert not (tmp_path / "nowhere").exists()
    assert gov(host, 0) == "powersave"


def test_pickle_undo_file(host, j, capsys):
    with open(j, "wb") as f:
        f.write(pickle.dumps([]))
    os.chmod(j, 0o600)
    before = open(j, "rb").read()
    assert main(["restore", j]) == 1
    assert "0.5.2" in capsys.readouterr().err
    assert open(j, "rb").read() == before


def test_journal_writable_by_others(host, j):
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 0
    os.chmod(j, 0o666)
    assert main(["restore", j]) == 1
    assert main(["-u", j, "cpu-governor", "schedutil", "C0"]) == 1
    assert gov(host, 0) == "performance"


def test_invalid_journal_later_in_chain(host, j):
    with open(j, "wb") as f:
        f.write(pickle.dumps([]))
    os.chmod(j, 0o600)
    assert main(["drop-caches", "restore", j]) == 1
    assert host.read("proc/sys/vm/drop_caches") == "0"


def test_unknown_action_in_journal(host, j):
    write_journal(j, HEADER + json.dumps({"undo": [{"action": "cpu-governor", "params": {
        "cpu": 0, "governor": "performance"}}]}) + "\n"
        + json.dumps({"undo": [{"action": "rm-rf", "params": {}}]}) + "\n")
    assert main(["restore", j]) == 1
    assert gov(host, 0) == "powersave"
    assert os.path.exists(j)


def test_undo_file_with_restore_is_usage_error(host, j, tmp_path):
    other = str(tmp_path / "other")
    write_journal(other, HEADER)
    assert main(["-u", j, "drop-caches", "restore", other]) == 2
    assert host.read("proc/sys/vm/drop_caches") == "0"
    assert not os.path.exists(j)


# ---------------------------------------------------------------- review fixes

def test_append_onto_unknown_action_record_refused(host, j):
    content = HEADER + '{"undo": [{"action": "rm-rf", "params": {}}]}\n'
    write_journal(j, content)
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 1
    assert gov(host, 0) == "powersave"
    assert open(j).read() == content


def test_append_onto_corrupt_record_refused(host, j):
    content = HEADER + "garbage\n" + '{"undo": []}\n'
    write_journal(j, content)
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 1
    assert gov(host, 0) == "powersave"
    assert open(j).read() == content


def test_same_journal_twice_in_restore_chain(host, j, capsys):
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 0
    assert main(["restore", j, "restore", j]) == 2
    assert gov(host, 0) == "performance"
    assert os.path.exists(j)


def test_restore_unlink_failure_reported(host, j, monkeypatch, capsys):
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 0

    def boom(p):
        raise PermissionError("nope")
    monkeypatch.setattr(os, "unlink", boom)
    assert main(["restore", j]) == 1
    assert "could not update journal" in capsys.readouterr().err
    assert gov(host, 0) == "powersave"


def test_record_undo_failure_appends_nothing(host, j, monkeypatch):
    from vfio_isolate.action import CPUGovernor
    assert main(["-u", j, "cpu-governor", "performance", "C0"]) == 0
    before = open(j).read()

    def boom(params):
        raise OSError("boom")
    monkeypatch.setattr(CPUGovernor, "record_undo", staticmethod(boom))
    with pytest.raises(OSError):
        main(["-u", j, "cpu-governor", "schedutil", "C0"])
    assert open(j).read() == before
    assert gov(host, 0) == "performance"


def test_write_ahead_when_execute_raises(host, j, monkeypatch):
    from vfio_isolate.cpu import CPU

    def boom(self, *a, **k):
        raise OSError("boom")
    monkeypatch.setattr(CPU, "set_governor", boom)
    with pytest.raises(OSError):
        main(["-u", j, "cpu-governor", "performance", "C0"])
    assert [n for n, _ in step_names(j)] == ["cpu-governor"]
