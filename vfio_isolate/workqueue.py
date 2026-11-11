"""Global unbound workqueue cpumask in /sys/devices/virtual/workqueue/."""
import os

from vfio_isolate import fsroot
from vfio_isolate.nodeset import CPUNodeSet


def _path(name: str) -> str:
    return fsroot.path("/sys/devices/virtual/workqueue", name)


def format_mask(cpus: CPUNodeSet) -> str:
    """Kernel hex mask: comma-separated 32-bit groups, highest first."""
    nodes = set(cpus)
    groups = (max(nodes) // 32 + 1) if nodes else 1
    parts = []
    for g in reversed(range(groups)):
        value = sum(1 << (n - g * 32) for n in nodes if n // 32 == g)
        parts.append(f"{value:08x}")
    return ",".join(parts)


def _read_mask(name: str) -> CPUNodeSet:
    with open(_path(name)) as f:
        return CPUNodeSet.from_mask(f.read())


def read_requested() -> CPUNodeSet:
    """The last written mask; kernels without cpumask_requested only have cpumask."""
    try:
        return _read_mask("cpumask_requested")
    except FileNotFoundError:
        return _read_mask("cpumask")


def read_isolated() -> CPUNodeSet:
    """CPUs in isolated cpuset partitions; empty where the kernel has no such file."""
    try:
        return _read_mask("cpumask_isolated")
    except FileNotFoundError:
        return CPUNodeSet()


def read_online() -> CPUNodeSet:
    with open(fsroot.path("/sys/devices/system/cpu/online")) as f:
        return CPUNodeSet(f.read())


def write_cpumask(cpus: CPUNodeSet):
    with open(_path("cpumask"), "w") as f:
        f.write(format_mask(cpus))
