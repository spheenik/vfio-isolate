from dataclasses import dataclass

from vfio_isolate.cpuset import CPUSet
from .action import Action, Execution


class CPUSetDelete(Action):
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
        cpu_set = CPUSet(p.cpuset_name)
        yield Execution(CPUSetCreate, CPUSetCreate.Param(
            cpuset_name=p.cpuset_name,
            cpus=cpu_set.get_cpus(),
            mems=cpu_set.get_mems(),
            cpu_exclusive=cpu_set.get_cpu_exclusive(),
            mem_exclusive=cpu_set.get_mem_exclusive(),
            mem_migrate=cpu_set.get_mem_migrate(),
            sched_load_balance=cpu_set.get_sched_load_balance()
        ))
