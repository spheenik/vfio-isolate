from dataclasses import dataclass

from .action import Action, Execution
from ..cpu import CPU


class CPUGovernor(Action):
    @dataclass
    class Param:
        cpu: CPU
        governor: str

    @classmethod
    def execute(cls, p: Param):
        p.cpu.set_governor(p.governor)

    @classmethod
    def record_undo(cls, p: Param):
        yield Execution(CPUGovernor, CPUGovernor.Param(
            cpu=p.cpu,
            governor=p.cpu.get_governor()
        ))
