import os
from typing import Generator

import psutil

from vfio_isolate import fsroot
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet, format_mask
from vfio_isolate import output
from vfio_isolate.output import print_debug


class IRQ:
    @staticmethod
    def base_path() -> str:
        return fsroot.path("/proc/irq")

    def __init__(self, number: int):
        self.number = number

    def __repr__(self):
        return f"IRQ {self.number} ({self.get_affinity().to_list_form()})"

    def __path(self, path: str = None):
        elements = [IRQ.base_path(), str(self.number)]
        if path:
            elements.append(path)
        return "/".join(elements)

    def exists(self):
        return os.path.exists(self.__path("smp_affinity_list"))

    def get_affinity(self) -> CPUNodeSet:
        with open(self.__path("smp_affinity_list"), "r") as f:
            return CPUNodeSet(f.read())

    def set_affinity(self, cpus: CPUNodeSet):
        try:
            with open(self.__path("smp_affinity_list"), "w") as f:
                f.write(cpus.to_list_form())
            output.failures.ok()
            return True
        except OSError as e:
            output.failures.irq(self.number, e)
            print_debug(f"unable to move set affinity of IRQ {self.number} to CPUSet {cpus}")
            return False

    def get_node(self) -> NUMANodeSet:
        with open(self.__path("node"), "r") as f:
            return NUMANodeSet(f.read())


class IRQS:

    @classmethod
    def active(cls) -> Generator[IRQ, None, None]:
        for file in os.listdir(IRQ.base_path()):
            if file.isnumeric():
                yield IRQ(int(file))


def _default_path() -> str:
    return fsroot.path("/proc/irq/default_smp_affinity")


def default_affinity_exists() -> bool:
    return os.path.exists(_default_path())


def read_default_affinity() -> CPUNodeSet:
    with open(_default_path()) as f:
        return CPUNodeSet.from_mask(f.read())


def write_default_affinity(cpus: CPUNodeSet):
    with open(_default_path(), "w") as f:
        f.write(format_mask(cpus))


IRQBALANCE_WARNING = ("vfio-isolate: warning: irqbalance is running and will overwrite IRQ affinities; stop it or ban the "
                      "VM's CPUs in its configuration (IRQBALANCE_BANNED_CPULIST)")


def irqbalance_running() -> bool:
    try:
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info.get('name') == 'irqbalance':
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False
