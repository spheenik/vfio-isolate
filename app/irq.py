import os

from app.nodeset import CPUNodeSet, NUMANodeSet


class IRQ:
    base_path = "/proc/irq"

    def __init__(self, number: int):
        self.number = number

    def __repr__(self):
        return f"IRQ {self.number} ({self.get_affinity().to_list_form()})"

    def __path(self, path: str = None):
        elements = [IRQ.base_path, str(self.number)]
        if path:
            elements.append(path)
        return "/".join(elements)

    def get_affinity(self) -> CPUNodeSet:
        with open(self.__path("smp_affinity_list"), "r") as f:
            return CPUNodeSet(f.read())

    def set_affinity(self, mask: CPUNodeSet):
        with open(self.__path("smp_affinity_list"), "w") as f:
            f.write(mask.to_list_form())

    def get_node(self) -> NUMANodeSet:
        with open(self.__path("node"), "r") as f:
            return NUMANodeSet(f.read())


class IRQS:

    @classmethod
    def active(cls):
        for file in os.listdir(IRQ.base_path):
            if file.isnumeric():
                yield IRQ(int(file))
