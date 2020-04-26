from app import fs
from app.cpu import CPUMask

class NumaNode:
    def __init__(self, number):
        self.number = number

    def sysfs_path(self, suffix):
        return "/sys/devices/system/node/node{}/{}".format(self.number, suffix)

    def do(self):
        read = fs.read(self.sysfs_path("cpulist"))
        print(read)
        cpu_mask = CPUMask(read)
        print(cpu_mask.cpus)



NumaNode(0).do()
