from dataclasses import dataclass
from enum import Enum, unique

from vfio_isolate.cpuset import CPUNodeSet
from vfio_isolate.irq import IRQ
from .action import Action, Execution


@unique
class IRQAffinityOperation(Enum):
    mask = 1,
    add = 2


class IRQAffinity(Action):
    @dataclass
    class Param:
        irq: IRQ
        operation: IRQAffinityOperation
        cpus: CPUNodeSet

    @classmethod
    def execute(cls, p: Param):
        if p.irq.exists():
            if p.operation == IRQAffinityOperation.add:
                p.irq.set_affinity(p.irq.get_affinity().union(p.cpus))
            elif p.operation == IRQAffinityOperation.mask:
                p.irq.set_affinity(p.irq.get_affinity().intersection(p.cpus.negation()))

    @classmethod
    def record_undo(cls, p: Param):
        if p.irq.exists():
            if p.operation == IRQAffinityOperation.add:
                added = p.irq.get_affinity().negation().intersection(p.cpus)
                if len(added):
                    yield Execution(IRQAffinity, IRQAffinity.Param(
                        irq=p.irq,
                        operation=IRQAffinityOperation.mask,
                        cpus=added
                    ))
            elif p.operation == IRQAffinityOperation.mask:
                masked = p.irq.get_affinity().intersection(p.cpus)
                if len(masked):
                    yield Execution(IRQAffinity, IRQAffinity.Param(
                        irq=p.irq,
                        operation=IRQAffinityOperation.add,
                        cpus=masked
                    ))
