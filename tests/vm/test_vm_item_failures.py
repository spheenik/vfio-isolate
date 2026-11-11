"""Per-item failure classification (FailureCollector) against the guest's real kernel.

Verifies that the errnos the kernel returns for kernel threads and IRQs match the table in
vfio_isolate/output.py.
The IRQ test also asserts that a real `irq-affinity mask` run prints no `warning:` lines
(only the EIO/ENOENT summaries).
"""
import errno
import os

import pytest

from vfio_isolate.cli import main

pytestmark = pytest.mark.vm

CG = "/sys/fs/cgroup"


def _rmdir(path):
    import time
    for _ in range(50):
        try:
            os.rmdir(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.1)
    os.rmdir(path)


def test_move_tasks_from_root_classifies_kernel_threads(tmp_path, capsys):
    j = str(tmp_path / "journal")
    path = f"{CG}/vfio-test-move"
    os.mkdir(path)
    try:
        rc = main(["-u", j, "move-tasks", "/", "/vfio-test-move"])
        err = capsys.readouterr().err
        with capsys.disabled():
            print("--- move-tasks stderr ---\n" + err)
        try:
            assert rc == 0
            assert "kernel thread" in err
            assert "warning:" not in err
        finally:
            assert main(["restore", j]) == 0
            capsys.readouterr()
    finally:
        _rmdir(path)


def _irq_table():
    names = {}
    with open("/proc/interrupts") as f:
        for line in f.readlines()[1:]:
            head, _, rest = line.partition(":")
            if head.strip().isdigit():
                names[int(head)] = " ".join(rest.split()[-3:])
    return names


def test_irq_affinity_errno_table(tmp_path, capsys):
    names = _irq_table()
    rows = []
    for d in sorted((x for x in os.listdir("/proc/irq") if x.isdigit()), key=int):
        n = int(d)
        p = f"/proc/irq/{n}/smp_affinity_list"
        try:
            with open(p) as f:
                orig = f.read().strip()
        except OSError as e:
            rows.append((n, names.get(n, "?"), f"read:{errno.errorcode.get(e.errno)}"))
            continue
        try:
            with open(p, "w") as f:
                f.write("0")
            res = "OK"
            with open(p, "w") as f:
                f.write(orig)
        except OSError as e:
            res = errno.errorcode.get(e.errno, str(e.errno))
        rows.append((n, names.get(n, "?"), res))
    with capsys.disabled():
        print("\n--- IRQ errno table (IRQ, name, result of writing '0') ---")
        for r in rows:
            print("IRQERRNO %4d  %-40s %s" % r)

    j = str(tmp_path / "journal")
    rc = main(["-u", j, "irq-affinity", "mask", "C0"])
    err = capsys.readouterr().err
    with capsys.disabled():
        print("--- irq-affinity mask C0 stderr ---\n" + err)
    assert rc == 0
    # EIO/ENOENT summaries are fine; an unexpected errno would show up as a warning
    assert not [l for l in err.splitlines() if "warning:" in l], err
    assert main(["restore", j]) == 0
