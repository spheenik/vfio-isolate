from dataclasses import dataclass

from .action import Action


class DropCaches(Action):
    @dataclass
    class Param:
        pass

    @classmethod
    def execute(cls, p: Param):
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3")
