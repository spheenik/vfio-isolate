from dataclasses import dataclass

from app.cpuset import CPUNodeSet, NUMANodeSet, CPUSet


@dataclass
class Param:
    cpuset_name: str
    cpus: CPUNodeSet
    mems: NUMANodeSet
    cpu_exclusive: bool
    mem_exclusive: bool
    mem_migrate: bool


def execute(p: Param):
    cpu_set = CPUSet(p.cpuset_name)
    cpu_set.create(p.cpus, p.mems)
    if p.cpus:
        cpu_set.set_cpus(p.cpus)
    if p.cpu_exclusive:
        cpu_set.set_cpu_exclusive(True)
    if p.mem_exclusive:
        cpu_set.set_mem_exclusive(True)
    if p.mem_migrate:
        cpu_set.set_mem_migrate(True)
