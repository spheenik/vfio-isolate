from dataclasses import dataclass

from vfio_isolate.cpuset import CPUSet
from .action import Action, Execution


class CPUSetCreate(Action):
    @dataclass
    class Param:
        cpuset_name: str

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        cpu_set.create()

    @classmethod
    def record_undo(cls, p):
        from .cpuset_delete import CPUSetDelete
        yield Execution(CPUSetDelete, CPUSetDelete.Param(cpuset_name=p.cpuset_name))
