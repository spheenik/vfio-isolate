"""Global unbound workqueue cpumask in /sys/devices/virtual/workqueue/."""
import os

from vfio_isolate import fsroot
from vfio_isolate.nodeset import CPUNodeSet, format_mask


def _path(name: str) -> str:
    return fsroot.path("/sys/devices/virtual/workqueue", name)


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
