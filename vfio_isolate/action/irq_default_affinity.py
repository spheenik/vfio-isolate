from dataclasses import dataclass
from enum import Enum, unique

from vfio_isolate import irq, workqueue
from vfio_isolate.nodeset import CPUNodeSet
from .action import Action, Execution, PreconditionError


@unique
class DefaultAffinityOperation(Enum):
    mask = 1
    add = 2


class IRQDefaultAffinity(Action):
    """Default affinity of new IRQs (/proc/irq/default_smp_affinity); queued by irq-affinity."""
    name = "irq-default-affinity"

    @dataclass
    class Param:
        operation: DefaultAffinityOperation
        cpus: CPUNodeSet

    @staticmethod
    def _new(p: Param, old: CPUNodeSet) -> CPUNodeSet:
        if p.operation == DefaultAffinityOperation.add:
            return old.union(p.cpus)
        return old.intersection(p.cpus.negation())

    @classmethod
    def _target(cls, p: Param):
        """(old, new) of the default; raises when a mask would leave no online CPU."""
        old = irq.read_default_affinity()
        new = cls._new(p, old)
        if p.operation == DefaultAffinityOperation.mask and not new.intersection(workqueue.read_online()):
            raise PreconditionError("no online CPU would remain in the default IRQ affinity")
        return old, new

    @classmethod
    def can_execute(cls, p: Param, ctx=None):
        if not irq.default_affinity_exists():
            return True
        if ctx is not None and ctx.depends(cls.reads(p)):
            if p.operation == DefaultAffinityOperation.mask:
                ctx.unchecked = True  # the refusal depends on earlier steps
            return True
        cls._target(p)
        return True

    @classmethod
    def execute(cls, p: Param):
        if irq.default_affinity_exists():
            irq.write_default_affinity(cls._target(p)[1])

    @classmethod
    def record_undo(cls, p: Param):
        if not irq.default_affinity_exists():
            return
        old = irq.read_default_affinity()
        if p.operation == DefaultAffinityOperation.mask:
            changed, undo = old.intersection(p.cpus), DefaultAffinityOperation.add
        else:
            changed, undo = p.cpus.intersection(old.negation()), DefaultAffinityOperation.mask
        if changed:
            yield Execution(IRQDefaultAffinity, IRQDefaultAffinity.Param(operation=undo, cpus=changed))

    @classmethod
    def touches(cls, p):
        return {("irq-default",)}

    @classmethod
    def describe(cls, p, ctx):
        from vfio_isolate.dryrun import unknown, AFTER_EARLIER
        if not irq.default_affinity_exists():
            return []
        if ctx.depends(cls.reads(p)):
            cpus = p.cpus.to_list_form()
            how = ("the current default without " if p.operation == DefaultAffinityOperation.mask
                   else "the current default plus ") + cpus
            return [f"set default IRQ affinity: {AFTER_EARLIER} -> {how}"]
        try:
            old, new = cls._target(p)
        except OSError as e:
            return [f"set default IRQ affinity: {unknown(e)}"]
        except PreconditionError as e:
            # a restore step the real restore refuses (keeps the step, exit 1): report, don't abort
            return [f"set default IRQ affinity: refused ({e})"]
        if old == new:
            return []
        return [f"set default IRQ affinity: {old.to_list_form()} -> {new.to_list_form()}"]
