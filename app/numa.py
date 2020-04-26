from app import fs
from app.cpu import CPUMask


class NumaNode:
    def __init__(self, number):
        self.number = number

    def sysfs_path(self, suffix):
        return "/sys/devices/system/node/node{}/{}".format(self.number, suffix)

    def get_cpumask(self):
        return CPUMask(fs.read(self.sysfs_path("cpulist")))


if __name__ == "__main__":
    print(NumaNode(0).get_cpumask())
