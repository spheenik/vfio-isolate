"""Per-item failures are reported without stopping the run (openspec/changes/error-reporting)."""
import builtins
import errno
import json

import pytest

from vfio_isolate.cli import main
from vfio_isolate.cpuset import CPUSet


@pytest.fixture
def host(fake_host):
    fake_host.patch_cgroup_fs()
    return fake_host


def fail_writes(monkeypatch, match, err):
    """Make opening for writing any path accepted by match(path) raise OSError(err)."""
    real_open = builtins.open

    def fake_open(path, mode="r", *a, **kw):
        if "w" in mode and match(str(path)):
            raise OSError(err, "injected")
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)


def irq_path(*numbers):
    return lambda p: any(p.endswith(f"/proc/irq/{n}/smp_affinity_list") for n in numbers)


def add_irqs(host, numbers, affinity="0-7"):
    for n in numbers:
        host.add_irq(n, affinity)


def aff(host, n):
    return host.read(f"proc/irq/{n}/smp_affinity_list").strip()


def lines(err):
    return [l for l in err.splitlines() if l]


def test_managed_irqs_summarized(host, monkeypatch, capsys):
    add_irqs(host, range(1, 7))
    fail_writes(monkeypatch, irq_path(2, 4, 6), errno.EIO)
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    err = lines(capsys.readouterr().err)
    assert err == ["vfio-isolate: 3 IRQs are kernel-managed or not movable and kept their affinity"]
    assert [aff(host, n) for n in (1, 3, 5)] == ["4-7"] * 3
    assert [aff(host, n) for n in (2, 4, 6)] == ["0-7"] * 3


def test_managed_irqs_eperm_summarized(host, monkeypatch, capsys):
    # kernel 7.2 returns EPERM for IRQs it does not let user space move
    add_irqs(host, range(1, 5))
    fail_writes(monkeypatch, irq_path(1, 3), errno.EPERM)
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    err = lines(capsys.readouterr().err)
    assert err == ["vfio-isolate: 2 IRQs are kernel-managed or not movable and kept their affinity"]
    assert [aff(host, n) for n in (1, 3)] == ["0-7"] * 2


def test_verbose_lists_irq_numbers(host, monkeypatch, capsys):
    add_irqs(host, range(1, 7))
    fail_writes(monkeypatch, irq_path(2, 4, 6), errno.EIO)
    assert main(["-v", "irq-affinity", "mask", "C0-3"]) == 0
    err = lines(capsys.readouterr().err)
    assert len(err) == 1
    assert err[0].startswith("vfio-isolate: 3 IRQs are kernel-managed")
    assert sorted(err[0].rsplit(": ", 1)[1].split(", ")) == ["2", "4", "6"]


def test_unexpected_irq_errno_warns_once(host, monkeypatch, capsys):
    add_irqs(host, range(1, 4))
    fail_writes(monkeypatch, irq_path(2), errno.EINVAL)
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    err = lines(capsys.readouterr().err)
    assert err == ["vfio-isolate: warning: IRQ 2: Invalid argument"]
    assert aff(host, 1) == "4-7" and aff(host, 3) == "4-7"


def test_gone_irq_summarized(host, monkeypatch, capsys):
    add_irqs(host, [1])
    fail_writes(monkeypatch, irq_path(1), errno.ENOENT)
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    assert lines(capsys.readouterr().err) == ["vfio-isolate: 1 IRQ is gone"]


def make_tasks(host, n):
    host.mkcg("a")
    host.mkcg("b")
    pids = list(range(900001, 900001 + n))
    (host.root / "sys/fs/cgroup/a/cgroup.procs").write_text("".join(f"{p}\n" for p in pids))
    return pids


def procs_path(p):
    return p.endswith("/b/cgroup.procs")


def test_repeated_unexpected_task_errno(host, monkeypatch, capsys):
    make_tasks(host, 5)
    fail_writes(monkeypatch, procs_path, errno.EBUSY)
    assert main(["move-tasks", "/a", "/b"]) == 1
    err = lines(capsys.readouterr().err)
    assert len(err) == 3
    assert err[0] == "vfio-isolate: warning: task 900001 (not running): Device or resource busy"
    assert err[1] == "vfio-isolate: move-tasks: no task could be moved"
    assert err[2] == "vfio-isolate: warning: ... and 4 more tasks: Device or resource busy"


def test_kernel_threads_summarized(host, monkeypatch, capsys):
    make_tasks(host, 3)
    fail_writes(monkeypatch, procs_path, errno.EINVAL)
    assert main(["-v", "move-tasks", "/a", "/b"]) == 0
    err = lines(capsys.readouterr().err)
    assert len(err) == 1
    assert err[0].startswith("vfio-isolate: 3 tasks are kernel threads and were not moved")
    assert "900001 (not running)" in err[0]


def test_nothing_printed_without_failures(host, capsys):
    add_irqs(host, [1])
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    assert capsys.readouterr().err == ""


def test_restore_reports_same_summary(host, monkeypatch, capsys, tmp_path):
    add_irqs(host, range(1, 4))
    j = str(tmp_path / "j")
    assert main(["-u", j, "irq-affinity", "mask", "C0-3"]) == 0
    assert aff(host, 1) == "4-7"
    capsys.readouterr()
    fail_writes(monkeypatch, irq_path(1, 2, 3), errno.EIO)
    assert main(["restore", j]) == 0
    err = capsys.readouterr().err
    assert "vfio-isolate: 3 IRQs are kernel-managed or not movable and kept their affinity" in err


def test_unexpected_errno_verbose_lists_only_repeats(host, monkeypatch, capsys):
    make_tasks(host, 3)
    fail_writes(monkeypatch, procs_path, errno.EBUSY)
    assert main(["-v", "move-tasks", "/a", "/b"]) == 1
    err = lines(capsys.readouterr().err)
    assert err[0] == "vfio-isolate: warning: task 900001 (not running): Device or resource busy"
    assert err[1] == "vfio-isolate: move-tasks: no task could be moved"
    assert err[2] == ("vfio-isolate: warning: ... and 2 more tasks: Device or resource busy"
                      ": 900002 (not running), 900003 (not running)")


def test_errnoless_oserror_does_not_say_success(host, monkeypatch, capsys):
    add_irqs(host, [1])
    real_open = builtins.open

    def fake_open(path, mode="r", *a, **kw):
        if "w" in mode and str(path).endswith("/proc/irq/1/smp_affinity_list"):
            raise OSError("weird failure")
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)
    assert main(["irq-affinity", "mask", "C0-3"]) == 1
    err = capsys.readouterr().err
    assert "Success" not in err and "weird failure" in err


def test_all_irqs_unexpected_error_exits_1(host, monkeypatch, capsys):
    add_irqs(host, range(1, 4))
    fail_writes(monkeypatch, irq_path(1, 2, 3), errno.EINVAL)
    assert main(["irq-affinity", "mask", "C0-3"]) == 1
    err = lines(capsys.readouterr().err)
    assert len(err) == 3
    assert err[0].startswith("vfio-isolate: warning: IRQ ") and err[0].endswith(": Invalid argument")
    assert err[1] == "vfio-isolate: irq-affinity: no IRQ could be changed"
    assert err[2] == "vfio-isolate: warning: ... and 2 more IRQs: Invalid argument"


def test_all_irqs_expected_error_exits_0(host, monkeypatch, capsys):
    add_irqs(host, range(1, 4))
    fail_writes(monkeypatch, irq_path(1, 2, 3), errno.EIO)
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    assert "no IRQ could be changed" not in capsys.readouterr().err


def test_partial_unexpected_irq_failure_exits_0(host, monkeypatch, capsys):
    add_irqs(host, range(1, 4))
    fail_writes(monkeypatch, irq_path(1, 2), errno.EINVAL)
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    assert "no IRQ could be changed" not in capsys.readouterr().err


def test_total_failure_does_not_stop_following_actions(host, monkeypatch, capsys):
    make_tasks(host, 2)
    fail_writes(monkeypatch, procs_path, errno.EBUSY)
    assert main(["move-tasks", "/a", "/b", "drop-caches"]) == 1
    assert "no task could be moved" in capsys.readouterr().err
    assert host.read("proc/sys/vm/drop_caches").strip() != ""
