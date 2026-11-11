"""hugepages command against the guest's real kernel pool (2M pages only).

Runs the real CLI as root. Every test asserts the pool read back from /sys/kernel/mm and
resets it to its starting value on teardown.
"""
import os
import subprocess
import sys
import time

import pytest

from vfio_isolate import journal
from vfio_isolate.cli import main

pytestmark = pytest.mark.vm

POOL = "/sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages"
MAP_2_PAGES = r"""
import mmap, os, sys
fd = os.open(sys.argv[1] + "/x", os.O_CREAT | os.O_RDWR)
os.ftruncate(fd, 2 << 21)
m = mmap.mmap(fd, 2 << 21)
for i in range(2):
    m[i << 21] = 7
print("mapped", flush=True)
sys.stdin.read()
"""


def pool():
    with open(POOL) as f:
        return int(f.read())


def set_pool(n):
    with open(POOL, "w") as f:
        f.write(str(n))


def wait_pool(n, seconds=10):
    for _ in range(int(seconds * 10)):
        if pool() == n:
            return True
        time.sleep(0.1)
    return pool() == n


@pytest.fixture
def j(tmp_path):
    return str(tmp_path / "journal")


@pytest.fixture
def start():
    """The pool size at the start; restored on teardown."""
    n = pool()
    yield n
    set_pool(n)


@pytest.fixture
def cleanup():
    fns = []
    yield fns.append
    for fn in reversed(fns):
        try:
            fn()
        except Exception:
            pass


def test_add_and_restore(j, start):
    assert main(["-u", j, "hugepages", "2M", "32M"]) == 0
    assert pool() == start + 16
    assert main(["restore", j]) == 0
    assert pool() == start


def test_shortfall_fails_and_leaves_no_record(j, start, capsys):
    with open("/proc/meminfo") as f:
        mem_kb = next(int(l.split()[1]) for l in f if l.startswith("MemTotal:"))
    impossible_kb = (mem_kb + 2047) // 2048 * 2048 + 128 * 1024  # more than the guest has memory
    assert main(["-u", j, "hugepages", "2M", f"{impossible_kb}K"]) == 1
    assert "in 2M pages; the pages were released" in capsys.readouterr().err
    assert pool() == start
    assert not os.path.exists(j) or journal.read_journal(j) == []


def test_release_with_pages_in_use(j, start, tmp_path, cleanup):
    mnt = str(tmp_path / "hugetlbfs")
    os.mkdir(mnt)
    child = []

    def teardown():
        if child:
            child[0].kill()
            child[0].wait()
        subprocess.run(["umount", mnt], capture_output=True)
        set_pool(start)
    cleanup(teardown)

    assert main(["-u", j, "hugepages", "2M", "16M"]) == 0
    assert pool() == start + 8
    subprocess.run(["mount", "-t", "hugetlbfs", "-o", "pagesize=2M", "none", mnt], check=True)
    p = subprocess.Popen([sys.executable, "-c", MAP_2_PAGES, mnt], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    child.append(p)
    assert p.stdout.readline().strip() == "mapped"

    assert main(["restore", j]) == 0     # the 2 pages in use stay until the child exits
    p.stdin.close()
    p.wait()
    os.unlink(mnt + "/x")
    subprocess.run(["umount", mnt], check=True)
    assert wait_pool(start)


NODE0 = "/sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"


def test_add_and_restore_on_node(j, start, cleanup):
    with open(NODE0) as f:
        node_start = int(f.read())

    def reset():
        with open(NODE0, "w") as f:
            f.write(str(node_start))
    cleanup(reset)
    assert main(["-u", j, "hugepages", "--node", "N0", "2M", "16M"]) == 0
    with open(NODE0) as f:
        assert int(f.read()) == node_start + 8
    assert main(["restore", j]) == 0
    with open(NODE0) as f:
        assert int(f.read()) == node_start
