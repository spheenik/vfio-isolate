from dataclasses import dataclass

from vfio_isolate.cpuset import CPUNodeSet, NUMANodeSet, CPUSet
from .action import Action, Execution, PreconditionError


class CPUSetModify(Action):
    name = "cpuset-modify"
    needs_cgroup = True

    @dataclass
    class Param:
        cpuset_name: str
        cpus: CPUNodeSet
        mems: NUMANodeSet

    @classmethod
    def can_execute(cls, p: Param):
        if not CPUSet(p.cpuset_name).exists():
            raise PreconditionError(f"cpuset {p.cpuset_name} does not exist")
        return True

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        if p.cpus is not None:
            cpu_set.set_cpus(p.cpus)
        if p.mems is not None:
            cpu_set.set_mems(p.mems)

    @classmethod
    def record_undo(cls, p):
        cpu_set = CPUSet(p.cpuset_name)
        yield Execution(CPUSetModify, CPUSetModify.Param(
            cpuset_name=p.cpuset_name,
            cpus=cpu_set.get_cpus(),
            mems=cpu_set.get_mems()
        ))
