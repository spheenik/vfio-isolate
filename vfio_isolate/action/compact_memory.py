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

    @classmethod
    def touches(cls, p):
        return {("caches",)}

    @classmethod
    def describe(cls, p, ctx):
        return ["compact memory (write 1 to /proc/sys/vm/compact_memory)"]
