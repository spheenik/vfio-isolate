import os
import re
from typing import Generator

from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet
from vfio_isolate.output import print_debug


class CPU:
    base_path = "/sys/devices/system/cpu"

    def __init__(self, number: int):
        self.number = number

    def __repr__(self):
        return f"CPU {self.number}"

    def __path(self, path: str = None):
        elements = [CPU.base_path, f"cpu{self.number}"]
        if path:
            elements.append(path)
        return "/".join(elements)

    def get_governor(self) -> str:
        with open(self.__path("cpufreq/scaling_governor"), "r") as f:
            return f.read().rstrip()

    def set_governor(self, governor: str):
        with open(self.__path("cpufreq/scaling_governor"), "w") as f:
            f.write(governor)

    def get_available_governors(self):
        with open(self.__path("cpufreq/scaling_available_governors"), "r") as f:
            return f.read().rstrip().split()


class CPUS:

    cpudir = re.compile("cpu(\\d+)")

    @classmethod
    def online(cls) -> Generator[CPU, None, None]:
        for file in os.listdir(CPU.base_path):
            m = CPUS.cpudir.match(file)
            if m is not None:
                yield CPU(int(m.group(1)))


if __name__ == "__main__":
    for c in CPUS.online():
        print(c.get_governor())
