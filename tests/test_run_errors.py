"""Root check and stopping-failure reporting (openspec/changes/error-reporting)."""
import builtins
import errno
import os

import pytest

from vfio_isolate import cli, privileges
from vfio_isolate.action import DropCaches
from vfio_isolate.cli import main

REAL_REQUIRE_ROOT = privileges.require_root


@pytest.fixture
def host(fake_host):
    fake_host.patch_cgroup_fs()
    return fake_host


@pytest.fixture
def non_root(monkeypatch):
    monkeypatch.setattr(privileges, "require_root", REAL_REQUIRE_ROOT)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)


def fail_drop_caches(monkeypatch, err=errno.EACCES):
    real_open = builtins.open

    def fake_open(path, mode="r", *a, **kw):
        if "w" in mode and str(path).endswith("/proc/sys/vm/drop_caches"):
            raise OSError(err, os.strerror(err), str(path))
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)


def test_non_root_refused(host, non_root, capsys):
    assert main(["drop-caches"]) == 1
    assert capsys.readouterr().err.strip() == "vfio-isolate: must be run as root"
    assert host.read("proc/sys/vm/drop_caches") == "0"


def test_non_root_restore_refused(host, non_root, capsys, tmp_path):
    assert main(["restore", str(tmp_path / "j")]) == 1
    assert capsys.readouterr().err.strip() == "vfio-isolate: must be run as root"


def test_help_needs_no_root(host, non_root, capsys):
    assert main(["--help"]) == 0
    assert "Usage" in capsys.readouterr().out


def test_oserror_with_undo_file(host, monkeypatch, capsys, tmp_path):
    host.mkcg("a")
    j = str(tmp_path / "j")
    fail_drop_caches(monkeypatch)
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a", "drop-caches"]) == 1
    err = capsys.readouterr().err
    assert len(err.strip().splitlines()) == 1
    assert "drop-caches failed: Permission denied" in err
    assert f'run "vfio-isolate restore {j}" to undo the changes made so far' in err


def test_oserror_without_undo_file(host, monkeypatch, capsys):
    host.mkcg("a")
    fail_drop_caches(monkeypatch)
    assert main(["cpuset-modify", "--cpus", "C0-3", "/a", "drop-caches"]) == 1
    err = capsys.readouterr().err
    assert "drop-caches failed: Permission denied" in err
    assert "changes made before the failure remain" in err
    assert "restore" not in err


def test_unexpected_exception(host, monkeypatch, capsys):
    def boom(p):
        raise RuntimeError("boom")

    monkeypatch.setattr(DropCaches, "execute", classmethod(lambda cls, p: boom(p)))
    assert main(["drop-caches"]) == 1
    err = capsys.readouterr().err
    assert "drop-caches failed: RuntimeError: boom" in err
    assert "use -d for a traceback" in err
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1


def test_unexpected_exception_debug_propagates(host, monkeypatch):
    def boom(p):
        raise RuntimeError("boom")

    monkeypatch.setattr(DropCaches, "execute", classmethod(lambda cls, p: boom(p)))
    with pytest.raises(RuntimeError):
        main(["-d", "drop-caches"])


def test_keyboard_interrupt_during_action(host, monkeypatch, capsys, tmp_path):
    host.mkcg("a")
    j = str(tmp_path / "j")

    def interrupt(p):
        raise KeyboardInterrupt

    monkeypatch.setattr(DropCaches, "execute", classmethod(lambda cls, p: interrupt(p)))
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a", "drop-caches"]) == 130
    err = capsys.readouterr().err
    assert "interrupted during drop-caches" in err
    assert f'vfio-isolate restore {j}' in err
    # every record written before the interrupt is still in the journal (drop-caches has no undo)
    assert len(open(j).read().splitlines()) == 2  # header + cpuset-modify record


def test_keyboard_interrupt_during_parsing(host, monkeypatch, capsys):
    def interrupt(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_parse_nodeset", interrupt)
    assert main(["cpuset-modify", "--cpus", "C0-3", "/a"]) == 130
    assert capsys.readouterr().err.strip() == "vfio-isolate: interrupted, nothing was changed"


def test_non_root_with_undo_file_changes_nothing(host, non_root, capsys, tmp_path):
    cg = host.mkcg("a")
    sd = host.enable_systemd()
    before = (cg / "cpuset.cpus").read_text()
    j = tmp_path / "j"
    assert main(["-u", str(j), "cpuset-modify", "--cpus", "C0-3", "/a"]) == 1
    assert capsys.readouterr().err.strip() == "vfio-isolate: must be run as root"
    assert not j.exists()
    assert sd.calls == []
    assert (cg / "cpuset.cpus").read_text() == before


def test_interrupt_during_second_restore_names_that_file(host, monkeypatch, capsys, tmp_path):
    from vfio_isolate.action import IRQAffinity
    host.add_irq(1)
    j1, j2 = str(tmp_path / "j1"), str(tmp_path / "j2")
    assert main(["-u", j1, "irq-affinity", "mask", "C0-3"]) == 0
    host.add_irq(2)
    assert main(["-u", j2, "irq-affinity", "mask", "C0-1"]) == 0
    capsys.readouterr()
    real = IRQAffinity.execute.__func__
    seen = []

    def execute(cls, p):
        seen.append(p)
        if len(seen) > 1:
            raise KeyboardInterrupt
        return real(cls, p)

    monkeypatch.setattr(IRQAffinity, "execute", classmethod(execute))
    assert main(["restore", j1, "restore", j2]) == 130
    err = capsys.readouterr().err
    assert not os.path.exists(j1)
    assert os.path.exists(j2)
    assert f"interrupted during restore of {j2}; it was left unchanged" in err
    assert j1 not in err


def test_precondition_failure_names_command_with_undo_file(host, capsys, tmp_path):
    host.mkcg("a")
    j = str(tmp_path / "j")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a", "move-tasks", "/a", "/missing"]) == 1
    err = capsys.readouterr().err
    assert "vfio-isolate: move-tasks failed:" in err
    assert "/missing" in err
    assert f"vfio-isolate restore {j}" in err


def test_precondition_failure_names_command_without_undo_file(host, capsys):
    host.mkcg("a")
    assert main(["cpuset-modify", "--cpus", "C0-3", "/a", "move-tasks", "/a", "/missing"]) == 1
    err = capsys.readouterr().err
    assert "vfio-isolate: move-tasks failed:" in err
    assert "changes made before the failure remain" in err


def test_first_action_precondition_failure_has_no_hint(host, capsys, tmp_path):
    host.mkcg("a")
    j = str(tmp_path / "j")
    assert main(["-u", j, "move-tasks", "/a", "/missing"]) == 1
    err = capsys.readouterr().err
    assert "move-tasks failed:" in err
    assert "restore" not in err
    assert "remain" not in err
