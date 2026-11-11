"""kthread-affinity against the guest's real kernel threads.

Runs the real CLI as root. The starting affinity of every movable kernel thread is restored on teardown.
"""
import glob
import os
import shutil
import subprocess
import time

import pytest

from vfio_isolate import kthread, workqueue
from vfio_isolate.cli import main
from vfio_isolate.nodeset import CPUNodeSet

pytestmark = pytest.mark.vm

CG = "/sys/fs/cgroup"


def rd(path):
    with open(path) as f:
        return f.read()


def affinity(pid):
    return CPUNodeSet(set(os.sched_getaffinity(pid)))


def online():
    return workqueue.read_online()


def upper_half():
    cpus = sorted(online())
    assert len(cpus) >= 4, "the guest needs at least 4 CPUs"
    return CPUNodeSet(set(cpus[len(cpus) // 2:]))


def pids_named(prefix):
    result = []
    for comm in glob.glob("/proc/[0-9]*/comm"):
        try:
            if rd(comm).strip().startswith(prefix):
                result.append(int(comm.split("/")[2]))
        except OSError:
            pass
    return sorted(result)


@pytest.fixture
def j(tmp_path):
    return str(tmp_path / "journal")


@pytest.fixture
def cleanup():
    fns = []
    yield fns.append
    for fn in reversed(fns):
        try:
            fn()
        except Exception:
            pass


@pytest.fixture
def start(cleanup):
    """kthreadd's affinity at the start. Every movable kernel thread's affinity is written back
    on teardown, whatever the test changed."""
    before = {}
    for t in kthread.list_kernel_threads():
        try:
            before[t.pid] = affinity(t.pid)
        except OSError:
            pass

    def restore_all():
        for pid, cpus in before.items():
            try:
                os.sched_setaffinity(pid, set(cpus))
            except OSError:
                pass  # exited meanwhile
    cleanup(restore_all)
    return before[kthread.KTHREADD_PID]


def test_kthreads_move_new_ones_inherit_and_restore(j, start, tmp_path, cleanup, capsys):
    gone = upper_half()
    keep = start.intersection(gone.negation())
    others = {pid: affinity(pid) for name in ("kswapd0", "khugepaged") for pid in pids_named(name)}
    assert main(["-u", j, "kthread-affinity", "mask", f"C{gone.to_list_form()}"]) == 0
    err = capsys.readouterr().err
    with capsys.disabled():
        print("--- kthread-affinity stderr ---\n" + err)
    assert "per-CPU" not in err and "warning:" not in err
    assert affinity(kthread.KTHREADD_PID) == keep
    for pid, before in others.items():
        assert affinity(pid) == before.intersection(gone.negation()), pid

    # a kernel thread created now inherits kthreadd's restricted affinity (needs loop and ext4)
    why = None
    if not shutil.which("mkfs.ext4"):
        why = "mkfs.ext4 is not available"
    elif any(subprocess.run(["modprobe", m], check=False).returncode for m in ("loop", "ext4")):
        why = "modprobe loop/ext4 failed"
    if why:
        with capsys.disabled():
            print(f"--- new-kernel-thread inherit check skipped: {why} ---")
    else:
        image, mnt = str(tmp_path / "fs.img"), str(tmp_path / "mnt")
        with open(image, "wb") as f:
            f.truncate(64 << 20)
        subprocess.run(["mkfs.ext4", "-q", image], check=True)
        os.mkdir(mnt)
        subprocess.run(["mount", "-o", "loop", image, mnt], check=True)
        cleanup(lambda: subprocess.run(["umount", mnt], check=False))
        deadline = time.time() + 5
        new = []
        while not new and time.time() < deadline:
            new = pids_named("jbd2/loop")
            time.sleep(0.1)
        assert new, "no jbd2/loop kernel thread appeared"
        for pid in new:
            assert affinity(pid) == keep, pid

    assert main(["restore", j]) == 0
    assert affinity(kthread.KTHREADD_PID) == start
    for pid, before in others.items():
        assert affinity(pid) == before, pid


@pytest.fixture
def partition_cg(cleanup):
    """Create a leaf cgroup for an isolated partition; torn down on teardown, and `+cpuset` in the
    root subtree_control is reverted if this test added it."""
    control = f"{CG}/cgroup.subtree_control"
    if "cpuset" not in rd(control).split():
        with open(control, "w") as f:
            f.write("+cpuset")

        def disable():
            try:
                with open(control, "w") as f:
                    f.write("-cpuset")
            except OSError:
                pass  # still used by another cgroup
        cleanup(disable)  # runs after the partition is removed (cleanups run in reverse)
    part = f"{CG}/vmtest-kt"
    os.mkdir(part)

    def remove():
        try:
            with open(f"{part}/cpuset.cpus.partition", "w") as f:
                f.write("member")
            with open(f"{part}/cpuset.cpus", "w") as f:
                f.write("\n")
        finally:
            os.rmdir(part)
    cleanup(remove)
    return part


def test_isolated_partition_is_refused(j, start, partition_cg, capsys):
    iso = upper_half()
    with open(f"{partition_cg}/cpuset.cpus", "w") as f:
        f.write(iso.to_list_form())
    with open(f"{partition_cg}/cpuset.cpus.partition", "w") as f:
        f.write("isolated")
    assert rd(f"{partition_cg}/cpuset.cpus.partition").strip() == "isolated"
    before = affinity(kthread.KTHREADD_PID)  # the kernel restricts kthreadd itself by now

    assert main(["-u", j, "kthread-affinity", "mask", f"C{iso.to_list_form()}"]) == 1
    assert "are in isolated cpuset partitions" in capsys.readouterr().err
    assert affinity(kthread.KTHREADD_PID) == before
    assert not os.path.exists(j) or not rd(j).splitlines()[1:]
