from dataclasses import dataclass


@dataclass
class Param:
    pass


def execute(p: Param):
    with open("/proc/sys/vm/drop_caches", "w") as f:
        f.write("3")


