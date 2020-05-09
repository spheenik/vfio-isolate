from dataclasses import dataclass


@dataclass
class Param:
    pass


def execute(p: Param):
    with open("/proc/sys/vm/compact_memory", "w") as f:
        f.write("1")
