from dataclasses import dataclass

from app.cpuset import CPUSet
from .action import Action


class MoveTasks(Action):
    @dataclass
    class Param:
        cpuset_from: str
        cpuset_to: str

    @classmethod
    def execute(cls, p: Param):
        set_from = CPUSet(p.cpuset_from)
        set_to = CPUSet(p.cpuset_to)
        set_to.add_all_from_cpuset(set_from)
