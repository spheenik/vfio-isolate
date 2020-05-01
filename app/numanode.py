

class NUMANode:
    def __init__(self, number):
        self.number = number

    def __repr__(self):
        return f"NumaNode {self.number} ({self.get_cpumask().to_list_representation()})"

    def __path(self, suffix):
        return f"/sys/devices/system/node/node{self.number}/{suffix}"

    def get_cpumask(self):
        from app.cpumask import CPUMask
        with open(self.__path("cpulist")) as f:
            return CPUMask(f.read())


if __name__ == "__main__":
    print(NUMANode(0))
