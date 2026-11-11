from dataclasses import dataclass

from .action import Action
from .. import fsroot


class DropCaches(Action):
    name = "drop-caches"
    @dataclass
    class Param:
        pass

    @classmethod
    def execute(cls, p: Param):
        with open(fsroot.path("/proc/sys/vm/drop_caches"), "w") as f:
            f.write("3")
