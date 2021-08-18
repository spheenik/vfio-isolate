import os
from abc import abstractmethod

import psutil

from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet
from vfio_isolate.output import *


class CPUSet:

    # these are assigned below
    mountpoint = None
    impl = None

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
        return f"{self.__class__} {self.name()}"

    def __path(self, path: str = None):
        elements = [CPUSet.mountpoint]
        elements.extend(self.path)
        if path:
            elements.append(path)
        return "/".join(elements)

    def open(self, file, mode='r'):
        return open(self.__path(file), mode)

    def name(self):
        return "/" + "/".join(self.path)

    def parent(self):
        if not self.path:
            raise Exception("no parent")
        else:
            return CPUSet(self.path[:-1])

    def create(self, cpus: CPUNodeSet = None, mems: NUMANodeSet = None):
        os.mkdir(self.__path())
        self.impl.on_create(self)
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

    def parents(self):
        n = 0
        while n < len(self.path):
            yield CPUSet(self.path[0:n])

    def get_cpus(self) -> CPUNodeSet:
        return self.impl.get_cpus(self)

    def set_cpus(self, mask: CPUNodeSet):
        self.impl.set_cpus(self, mask)

    def get_mems(self) -> NUMANodeSet:
        return self.impl.get_mems(self)

    def set_mems(self, mask: NUMANodeSet):
        self.impl.set_mems(self, mask)

    def get_cpu_exclusive(self):
        return self.impl.get_cpu_exclusive(self)

    def set_cpu_exclusive(self, value):
        self.impl.set_cpu_exclusive(self, value)

    def get_mem_exclusive(self):
        return self.impl.get_mem_exclusive(self)

    def set_mem_exclusive(self, value):
        self.impl.set_mem_exclusive(self, value)

    def get_mem_migrate(self):
        return self.impl.get_mem_migrate(self)

    def set_mem_migrate(self, value):
        self.impl.set_mem_migrate(self, value)

    def get_sched_load_balance(self):
        return self.impl.get_sched_load_balance(self)

    def set_sched_load_balance(self, value):
        self.impl.set_sched_load_balance(self, value)

    def pids(self):
        return self.impl.pids(self)

    def add_pid(self, pid: int, silent=False):
        try:
            if not silent:
                print_verbose(f"moving PID {pid} to CPUSet {self.name()}")
            self.impl.add_pid(self, pid)
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


class CGroupV1:

    @staticmethod
    def on_create(cpuset: CPUSet):
        pass

    @staticmethod
    def get_cpus(cpuset: CPUSet) -> CPUNodeSet:
        with cpuset.open("cpuset.cpus", "r") as f:
            return CPUNodeSet(f.read())

    @staticmethod
    def set_cpus(cpuset: CPUSet, mask: CPUNodeSet):
        with cpuset.open("cpuset.cpus", "w") as f:
            f.write(mask.to_list_form())

    @staticmethod
    def get_mems(cpuset: CPUSet) -> NUMANodeSet:
        with cpuset.open("cpuset.mems", "r") as f:
            return NUMANodeSet(f.read())

    @staticmethod
    def set_mems(cpuset: CPUSet, mask: NUMANodeSet):
        with cpuset.open("cpuset.mems", "w") as f:
            f.write(mask.to_list_form())

    @staticmethod
    def get_cpu_exclusive(cpuset: CPUSet):
        with cpuset.open("cpuset.cpu_exclusive", "r") as f:
            return f.read() != "0"

    @staticmethod
    def set_cpu_exclusive(cpuset: CPUSet, value):
        with cpuset.open("cpuset.cpu_exclusive", "w") as f:
            f.write("1" if value else "0")

    @staticmethod
    def get_mem_exclusive(cpuset: CPUSet):
        with cpuset.open("cpuset.mem_exclusive", "r") as f:
            return f.read() != "0"

    @staticmethod
    def set_mem_exclusive(cpuset: CPUSet, value):
        with cpuset.open("cpuset.mem_exclusive", "w") as f:
            f.write("1" if value else "0")

    @staticmethod
    def get_mem_migrate(cpuset: CPUSet):
        with cpuset.open("cpuset.memory_migrate", "r") as f:
            return f.read() != "0"

    @staticmethod
    def set_mem_migrate(cpuset: CPUSet, value):
        with cpuset.open("cpuset.memory_migrate", "w") as f:
            f.write("1" if value else "0")

    @staticmethod
    def get_sched_load_balance(cpuset: CPUSet):
        with cpuset.open("cpuset.sched_load_balance", "r") as f:
            return f.read() != "0"

    @staticmethod
    def set_sched_load_balance(cpuset: CPUSet, value):
        with cpuset.open("cpuset.sched_load_balance", "w") as f:
            f.write("1" if value else "0")

    @staticmethod
    def pids(cpuset: CPUSet):
        with cpuset.open("tasks", "r") as f:
            for pid in f:
                yield int(pid.strip())

    @staticmethod
    def add_pid(cpuset: CPUSet, pid: int):
        with cpuset.open("tasks", "w") as f:
            f.write(str(pid))


class CGroupV2:

    @staticmethod
    def on_create(cpuset: CPUSet):
        pass

    @staticmethod
    def is_controller_enabled(cpuset: CPUSet, controller):
        with cpuset.open("cgroup.controllers", "r") as f:
            for c in f:
                if controller == c:
                    return True
        return False

    @staticmethod
    def enable_controller(cpuset: CPUSet, controller, enable=True):
        prefix = "+" if enable else "-"
        with cpuset.open("cgroup.subtree_control", "w") as f:
            f.write(f"{prefix}{controller}")

    @staticmethod
    def ensure_cpuset_controller_enabled(cpuset: CPUSet):
        if not CGroupV2.is_controller_enabled(cpuset, "cpuset"):
            CGroupV2.enable_controller(cpuset, "cpuset")

    @staticmethod
    def get_cpus(cpuset: CPUSet) -> CPUNodeSet:
        CGroupV2.ensure_cpuset_controller_enabled(cpuset)
        with cpuset.open("cpuset.cpus.effective", "r") as f:
            return CPUNodeSet(f.read())

    @staticmethod
    def set_cpus(cpuset: CPUSet, mask: CPUNodeSet):
        CGroupV2.ensure_cpuset_controller_enabled(cpuset)
        with cpuset.open("cpuset.cpus", "w") as f:
            f.write(mask.to_list_form())

    @staticmethod
    def get_mems(cpuset: CPUSet) -> NUMANodeSet:
        CGroupV2.ensure_cpuset_controller_enabled(cpuset)
        with cpuset.open("cpuset.mems.effective", "r") as f:
            return NUMANodeSet(f.read())

    @staticmethod
    def set_mems(cpuset: CPUSet, mask: NUMANodeSet):
        CGroupV2.ensure_cpuset_controller_enabled(cpuset)
        with cpuset.open("cpuset.mems", "w") as f:
            f.write(mask.to_list_form())

    @staticmethod
    def get_cpu_exclusive(cpuset: CPUSet):
        return False

    @staticmethod
    def set_cpu_exclusive(cpuset: CPUSet, value):
        pass

    @staticmethod
    def get_mem_exclusive(cpuset: CPUSet):
        return False

    @staticmethod
    def set_mem_exclusive(cpuset: CPUSet, value):
        pass

    @staticmethod
    def get_mem_migrate(cpuset: CPUSet):
        return False

    @staticmethod
    def set_mem_migrate(cpuset: CPUSet, value):
        pass

    @staticmethod
    def get_sched_load_balance(cpuset: CPUSet):
        return False

    @staticmethod
    def set_sched_load_balance(cpuset: CPUSet, value):
        pass

    @staticmethod
    def pids(cpuset: CPUSet):
        with cpuset.open("cgroup.procs", "r") as f:
            for pid in f:
                yield int(pid.strip())

    @staticmethod
    def add_pid(cpuset: CPUSet, pid: int):
        with cpuset.open("cgroup.procs", "w") as f:
            f.write(str(pid))


# SETUP
def setup():
    for part in psutil.disk_partitions(True):
        fstype = part.fstype
        if fstype.startswith("cgroup"):
            CPUSet.mountpoint = part.mountpoint
            if fstype.endswith("2"):
                CPUSet.impl = CGroupV2
            else:
                CPUSet.impl = CGroupV1
            return
    raise RuntimeError("cgroups not found")


setup()
