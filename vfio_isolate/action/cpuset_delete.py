from dataclasses import dataclass

from vfio_isolate.cpuset import CPUSet
from .action import Action, Execution


class CPUSetDelete(Action):
    needs_cgroup = True

    @dataclass
    class Param:
        cpuset_name: str

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        cpu_set.parent().add_all_from_cpuset(cpu_set)
        cpu_set.remove()

    @classmethod
    def record_undo(cls, p):
        from .cpuset_create import CPUSetCreate
        from .cpuset_modify import CPUSetModify

        yield Execution(CPUSetCreate, CPUSetCreate.Param(
            cpuset_name=p.cpuset_name
        ))

        cpu_set = CPUSet(p.cpuset_name)
        yield Execution(CPUSetModify, CPUSetModify.Param(
            cpuset_name=p.cpuset_name,
            cpus=cpu_set.get_cpus(),
            mems=cpu_set.get_mems()
        ))
