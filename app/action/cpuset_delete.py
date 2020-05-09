from dataclasses import dataclass

from app.cpuset import CPUSet


@dataclass
class Param:
    cpuset_name: str


def execute(p: Param):
    cpu_set = CPUSet(p.cpuset_name)
    cpu_set.parent().add_all_from_cpuset(cpu_set)
    cpu_set.remove()
