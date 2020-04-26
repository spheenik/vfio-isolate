from app import fs
from app.cpu import CPUMask


class CPUSet:
    base_path = "/sys/fs/cgroup/cpuset"

    def __init__(self, name=None):
        if not name:
            self.name = "_ROOT"
            self.base_path = CPUSet.base_path
        else:
            self.name = name
            self.base_path = CPUSet.base_path + "/" + name

    def create(self):
        fs.mkdir(self.base_path)
        return self

    def remove(self):
        fs.rmdir(self.base_path)

    def set_cpus(self, mask: CPUMask):
        fs.write(self.base_path + "/cpuset.cpus", mask.to_list_representation())

    def set_cpu_exclusive(self, value):
        fs.write(self.base_path + "/cpuset.cpu_exclusive", "1" if value else "0")

    def set_mem_exclusive(self, value):
        fs.write(self.base_path + "/cpuset.mem_exclusive", "1" if value else "0")

    def set_sched_load_balance(self, value):
        fs.write(self.base_path + "/cpuset.sched_load_balance", "1" if value else "0")


if __name__ == "__main__":
    pass
