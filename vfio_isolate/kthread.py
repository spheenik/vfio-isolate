"""Kernel threads: listing (PF_KTHREAD in /proc/<pid>/stat) and their CPU affinity."""
import os
from dataclasses import dataclass
from typing import List, Tuple

from vfio_isolate import fsroot
from vfio_isolate.nodeset import CPUNodeSet

PF_KTHREAD = 0x00200000
PF_NO_SETAFFINITY = 0x04000000  # per-CPU threads: the kernel refuses any affinity change with EINVAL
KTHREADD_PID = 2


@dataclass(frozen=True)
class KThread:
    pid: int
    comm: str


def parse_stat(text: str) -> Tuple[str, int, int]:
    """(comm, flags, starttime) of a /proc/<pid>/stat line. comm sits in parentheses and may itself contain
    spaces and parentheses, so the fields after it start behind the last ')'."""
    start, end = text.index("("), text.rindex(")")
    rest = text[end + 1:].split()
    # fields: pid (comm) state ppid pgrp session tty_nr tpgid flags ...; flags is field 9
    # starttime is field 22; (pid, starttime) identifies a thread for the life of the boot
    return text[start + 1:end], int(rest[6]), int(rest[19])


def read_stat(pid: int) -> Tuple[str, int, int]:
    with open(fsroot.path("/proc", str(pid), "stat")) as f:
        return parse_stat(f.read())


def comm(pid: int) -> str:
    try:
        return read_stat(pid)[0]
    except (OSError, ValueError, IndexError):
        return "?"


def list_kernel_threads() -> List[KThread]:
    """The kernel threads whose affinity can be changed, kthreadd (PID 2) first, the others by PID.
    Threads with PF_NO_SETAFFINITY (per-CPU ones) are left out; kthreadd never is."""
    found = []
    for name in os.listdir(fsroot.path("/proc")):
        if not name.isdigit():
            continue
        try:
            name_, flags, _ = read_stat(int(name))
        except (OSError, ValueError, IndexError):
            continue  # exited meanwhile, or not readable
        if flags & PF_KTHREAD and (int(name) == KTHREADD_PID or not flags & PF_NO_SETAFFINITY):
            found.append(KThread(int(name), name_))
    return sorted(found, key=lambda t: (t.pid != KTHREADD_PID, t.pid))


def get_affinity(pid: int) -> CPUNodeSet:
    return CPUNodeSet(set(os.sched_getaffinity(pid)))


def set_affinity(pid: int, cpus: CPUNodeSet):
    os.sched_setaffinity(pid, set(cpus))
