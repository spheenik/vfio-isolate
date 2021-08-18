from dataclasses import dataclass

from vfio_isolate.cpuset import CPUNodeSet, NUMANodeSet, CPUSet
from .action import Action, Execution


class CPUSetModify(Action):
    @dataclass
    class Param:
        cpuset_name: str
        cpus: CPUNodeSet
        mems: NUMANodeSet
        cpu_exclusive: bool
        mem_exclusive: bool
        mem_migrate: bool
        sched_load_balance: bool

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        if p.cpus is not None:
            cpu_set.set_cpus(p.cpus)
        if p.mems is not None:
            cpu_set.set_mems(p.mems)
        if p.cpu_exclusive is not None:
            cpu_set.set_cpu_exclusive(p.cpu_exclusive)
        if p.mem_exclusive is not None:
            cpu_set.set_mem_exclusive(p.mem_exclusive)
        if p.mem_migrate is not None:
            cpu_set.set_mem_migrate(p.mem_migrate)
        if p.sched_load_balance is not None:
            cpu_set.set_sched_load_balance(p.sched_load_balance)

    @classmethod
    def record_undo(cls, p):
        cpu_set = CPUSet(p.cpuset_name)
        yield Execution(CPUSetModify, CPUSetModify.Param(
            cpuset_name=p.cpuset_name,
            cpus=cpu_set.get_cpus(),
            mems=cpu_set.get_mems(),
            cpu_exclusive=cpu_set.get_cpu_exclusive(),
            mem_exclusive=cpu_set.get_mem_exclusive(),
            mem_migrate=cpu_set.get_mem_migrate(),
            sched_load_balance=cpu_set.get_sched_load_balance()
        ))
