from dataclasses import dataclass

from vfio_isolate.cpuset import CPUSet
from .action import Action, Execution, PreconditionError


class CPUSetCreate(Action):
    name = "cpuset-create"
    needs_cgroup = True

    @dataclass
    class Param:
        cpuset_name: str

    @classmethod
    def can_execute(cls, p: Param):
        if CPUSet(p.cpuset_name).exists():
            raise PreconditionError(f"cpuset {p.cpuset_name} already exists")
        return True

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        if cpu_set.exists():
            # undo of a delete that failed before rmdir
            return
        cpu_set.create()

    @classmethod
    def record_undo(cls, p):
        from .cpuset_delete import CPUSetDelete
        yield Execution(CPUSetDelete, CPUSetDelete.Param(cpuset_name=p.cpuset_name))
