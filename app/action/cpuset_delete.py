from dataclasses import dataclass

from app.cpuset import CPUSet
from .action import Action


class CPUSetDelete(Action):
    @dataclass
    class Param:
        cpuset_name: str

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        cpu_set.parent().add_all_from_cpuset(cpu_set)
        cpu_set.remove()
