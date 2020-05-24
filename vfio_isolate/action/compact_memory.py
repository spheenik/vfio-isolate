from dataclasses import dataclass

from .action import Action


class CompactMemory(Action):
    @dataclass
    class Param:
        pass

    @classmethod
    def execute(cls, p: Param):
        with open("/proc/sys/vm/compact_memory", "w") as f:
            f.write("1")
