from dataclasses import dataclass

from .action import Action
from .. import fsroot


class CompactMemory(Action):
    name = "compact-memory"
    @dataclass
    class Param:
        pass

    @classmethod
    def execute(cls, p: Param):
        with open(fsroot.path("/proc/sys/vm/compact_memory"), "w") as f:
            f.write("1")
