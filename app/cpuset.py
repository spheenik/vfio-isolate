import psutil
import os
from app.cpumask import CPUMask
from app.output import *


class CPUSet:
    base_path = "/sys/fs/cgroup/cpuset"
    root = None  # assigned down below

    def __init__(self, name=None):
        if not name:
            self.path = []
        elif isinstance(name, str):
            self.path = [name]
        elif isinstance(name, list):
            self.path = [str(x) for x in name]
        else:
            raise Exception("cannot initialize CPUSet")

    def __path(self, path: str = None):
        elements = [CPUSet.base_path]
        elements.extend(self.path)
        if path:
            elements.append(path)
        return "/".join(elements)

    def name(self):
        return "/" + "/".join(self.path)

    def create(self):
        os.mkdir(self.__path())

    def remove(self):
        os.rmdir(self.__path())

    def set_cpus(self, mask: CPUMask):
        with open(self.__path("cpuset.cpus"), "w") as f:
            f.write(mask.to_list_representation())

    def set_cpu_exclusive(self, value):
        with open(self.__path("cpuset.cpu_exclusive"), "w") as f:
            f.write("1" if value else "0")

    def set_mem_exclusive(self, value):
        with open(self.__path("cpuset.mem_exclusive"), "w") as f:
            f.write("1" if value else "0")

    def set_sched_load_balance(self, value):
        with open(self.__path("cpuset.sched_load_balance"), "w") as f:
            f.write("1" if value else "0")

    def pids(self):
        with open(self.__path("tasks")) as f:
            for pid in f:
                yield int(pid.strip())

    def add_pid(self, pid: int):
        try:
            with open(self.__path("tasks"), "w") as f:
                f.write(str(pid))
            return True
        except OSError:
            p = psutil.Process(pid)
            output_verbose(f"unable to move PID {pid} ({p.name() if p.is_running() else 'not running'}) to CPUSet {self.name()}")
            return False

    def add_all_from_cpuset(self, other):
        for pid in other.pids():
            self.add_pid(pid)


CPUSet.root = CPUSet()


if __name__ == "__main__":
    test_set = CPUSet("test")

    test_set.add_all_from_cpuset(CPUSet.root)
    CPUSet.root.add_all_from_cpuset(test_set)

