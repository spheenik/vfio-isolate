"""Rolled-back actions leave no journal record; runs are serialized
(openspec/changes/hugepages/specs/undo-journal/spec.md)."""
import fcntl
import os
import threading

import pytest

from vfio_isolate import fsroot, journal
from vfio_isolate.action import CPUGovernor, DropCaches, Execution, RolledBackError
from vfio_isolate.cpu import CPU
from vfio_isolate.cli import main


@pytest.fixture
def host(fake_host):
    fake_host.patch_cgroup_fs()
    return fake_host


@pytest.fixture
def rolling_back(monkeypatch):
    def execute(p):
        raise RolledBackError("could not get 8 pages, rolled back")

    # a real undo step, so the action has a journal record
    def record_undo(p):
        yield Execution(CPUGovernor, CPUGovernor.Param(cpu=CPU(0), governor="x"))

    monkeypatch.setattr(DropCaches, "execute", staticmethod(execute))
    monkeypatch.setattr(DropCaches, "record_undo", staticmethod(record_undo))


def gov(host, n):
    return host.read(f"sys/devices/system/cpu/cpu{n}/cpufreq/scaling_governor").strip()


def test_rolled_back_keeps_earlier_records(host, rolling_back, tmp_path, capsys):
    j = str(tmp_path / "j")
    before = gov(host, 1)
    assert main(["-u", j, "cpu-governor", "performance", "C1", "drop-caches"]) == 1
    err = capsys.readouterr().err
    assert "drop-caches failed: could not get 8 pages, rolled back" in err
    assert f'run "vfio-isolate restore {j}"' in err
    assert "nothing was changed" not in err
    assert len(journal.read_journal(j)) == 1
    assert gov(host, 1) == "performance"
    assert main(["restore", j]) == 0
    assert gov(host, 1) == before


def test_rolled_back_first_change_says_nothing_changed(host, rolling_back, tmp_path, capsys):
    j = str(tmp_path / "j")
    assert main(["-u", j, "drop-caches"]) == 1
    err = capsys.readouterr().err
    assert err.strip() == ("vfio-isolate: drop-caches failed: could not get 8 pages, "
                           "rolled back; nothing was changed")
    assert journal.read_journal(j) == []


def test_discard_last_noop_without_append(tmp_path):
    path = str(tmp_path / "j")
    with journal.open_for_append(path) as a:
        a.discard_last()
        a.append([])
        a.discard_last()
    assert journal.read_journal(path) == []


def test_run_lock_blocks_second_run(host, monkeypatch, capsys):
    lock = fsroot.path("/run/vfio-isolate.lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    result = []
    t = threading.Thread(target=lambda: result.append(main(["drop-caches"])), daemon=True)
    try:
        t.start()
        t.join(0.3)
        assert t.is_alive() and not result
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    t.join(5)
    assert result == [0]


def _gov_journal(host, tmp_path):
    j = str(tmp_path / "j")
    assert main(["-u", j, "cpu-governor", "performance", "C1"]) == 0
    return j


def test_restore_journal_deleted_before_lock(host, tmp_path, monkeypatch, capsys):
    from vfio_isolate import cli
    j = _gov_journal(host, tmp_path)
    capsys.readouterr()
    real_run = cli.Executor.run

    def run(self):
        os.unlink(j)  # another restore finished between parse and lock
        return real_run(self)

    monkeypatch.setattr(cli.Executor, "run", run)
    steps = []
    monkeypatch.setattr(CPUGovernor, "execute", classmethod(lambda cls, p: steps.append(p)))
    assert main(["restore", j]) == 0
    assert f"restore: {j}: already restored" in capsys.readouterr().err
    assert steps == []


def test_restore_replays_record_appended_before_lock(host, tmp_path, monkeypatch):
    from vfio_isolate import cli
    j = _gov_journal(host, tmp_path)
    before = gov(host, 2)
    real_run = cli.Executor.run

    def run(self):
        # a concurrent run appended its record after the restore parsed the file
        with journal.open_for_append(j) as a:
            a.append([Execution(CPUGovernor, CPUGovernor.Param(cpu=CPU(2), governor=before))])
        host._write("sys/devices/system/cpu/cpu2/cpufreq/scaling_governor", "performance")
        return real_run(self)

    monkeypatch.setattr(cli.Executor, "run", run)
    assert main(["restore", j]) == 0
    assert gov(host, 2) == before
    assert not os.path.exists(j)
