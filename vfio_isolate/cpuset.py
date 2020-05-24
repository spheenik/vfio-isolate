import os

import psutil

from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet
from vfio_isolate.output import *


class CPUSet:
    base_path = "/sys/fs/cgroup/cpuset"
    root = None  # assigned down below

    def __init__(self, name=None):
        if not name:
            self.path = []
        elif isinstance(name, str):
            self.path = list(filter(None, name.split("/")))
        elif isinstance(name, list):
            self.path = [str(x) for x in name]
        else:
            raise Exception("cannot initialize CPUSet")

    def __repr__(self):
        return f"CPUSet {self.name()}"

    def __path(self, path: str = None):
        elements = [CPUSet.base_path]
        elements.extend(self.path)
        if path:
            elements.append(path)
        return "/".join(elements)

    def name(self):
        return "/" + "/".join(self.path)

    def parent(self):
        if not self.path:
            raise Exception("no parent")
        else:
            return CPUSet(self.path[:-1])

    def create(self, cpus: CPUNodeSet = None, mems: NUMANodeSet = None):
        os.mkdir(self.__path())
        if cpus:
            self.set_cpus(cpus)
        else:
            self.set_cpus(self.parent().get_cpus())
        if mems:
            self.set_mems(mems)
        else:
            self.set_mems(self.parent().get_mems())

    def remove(self):
        os.rmdir(self.__path())

    def get_cpus(self) -> CPUNodeSet:
        with open(self.__path("cpuset.cpus"), "r") as f:
            return CPUNodeSet(f.read())

    def set_cpus(self, mask: CPUNodeSet):
        with open(self.__path("cpuset.cpus"), "w") as f:
            f.write(mask.to_list_form())

    def get_mems(self) -> NUMANodeSet:
        with open(self.__path("cpuset.mems"), "r") as f:
            return NUMANodeSet(f.read())

    def set_mems(self, mask: NUMANodeSet):
        with open(self.__path("cpuset.mems"), "w") as f:
            f.write(mask.to_list_form())

    def get_cpu_exclusive(self):
        with open(self.__path("cpuset.cpu_exclusive"), "r") as f:
            return f.read() != "0"

    def set_cpu_exclusive(self, value):
        with open(self.__path("cpuset.cpu_exclusive"), "w") as f:
            f.write("1" if value else "0")

    def get_mem_exclusive(self):
        with open(self.__path("cpuset.mem_exclusive"), "r") as f:
            return f.read() != "0"

    def set_mem_exclusive(self, value):
        with open(self.__path("cpuset.mem_exclusive"), "w") as f:
            f.write("1" if value else "0")

    def get_mem_migrate(self):
        with open(self.__path("cpuset.memory_migrate"), "r") as f:
            return f.read() != "0"

    def set_mem_migrate(self, value):
        with open(self.__path("cpuset.memory_migrate"), "w") as f:
            f.write("1" if value else "0")

    def get_sched_load_balance(self):
        with open(self.__path("cpuset.sched_load_balance"), "r") as f:
            return f.read() != "0"

    def set_sched_load_balance(self, value):
        with open(self.__path("cpuset.sched_load_balance"), "w") as f:
            f.write("1" if value else "0")

    def pids(self):
        with open(self.__path("tasks")) as f:
            for pid in f:
                yield int(pid.strip())

    def add_pid(self, pid: int, silent=False):
        try:
            if not silent:
                print_verbose(f"moving PID {pid} to CPUSet {self.name()}")
            with open(self.__path("tasks"), "w") as f:
                f.write(str(pid))
            return True
        except OSError:
            try:
                name = psutil.Process(pid).name()
            except psutil.NoSuchProcess:
                name = "not running"
            print_debug(f"unable to move PID {pid} ({name}) to CPUSet {self.name()}")
            return False

    def add_all_from_cpuset(self, other):
        print_verbose(f"moving all processes from CPUSet {other.name()} to CPUSet {self.name()}")
        for pid in other.pids():
            self.add_pid(pid, True)


CPUSet.root = CPUSet()
