from dataclasses import dataclass

from vfio_isolate.cpuset import CPUSet
from .action import Action, Execution


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

    @classmethod
    def record_undo(cls, p):
        yield Execution(MoveTasks, MoveTasks.Param(cpuset_from=p.cpuset_to, cpuset_to=p.cpuset_from))
