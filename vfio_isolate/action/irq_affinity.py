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
    name = "irq-affinity"
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
                remaining = p.irq.get_affinity().intersection(p.cpus.negation())
                if not remaining:
                    # empty: set all but the masked ones
                    p.irq.set_affinity(p.cpus.negation())
                else:
                    # not empty: set
                    p.irq.set_affinity(remaining)

    @classmethod
    def record_undo(cls, p: Param):
        if p.irq.exists():
            if p.operation == IRQAffinityOperation.add:
                added = p.irq.get_affinity().negation().intersection(p.cpus)
                if added:
                    yield Execution(IRQAffinity, IRQAffinity.Param(
                        irq=p.irq,
                        operation=IRQAffinityOperation.mask,
                        cpus=added
                    ))
            elif p.operation == IRQAffinityOperation.mask:
                masked = p.irq.get_affinity().intersection(p.cpus)
                if masked:
                    yield Execution(IRQAffinity, IRQAffinity.Param(
                        irq=p.irq,
                        operation=IRQAffinityOperation.add,
                        cpus=masked
                    ))
                    if masked == p.irq.get_affinity():
                        # would mask all, remove all but the masked ones
                        yield Execution(IRQAffinity, IRQAffinity.Param(
                            irq=p.irq,
                            operation=IRQAffinityOperation.mask,
                            cpus=p.cpus.negation().intersection(masked.negation())
                        ))

    batch = True

    @classmethod
    def _new_affinity(cls, p: Param, current):
        """What execute would write for an IRQ whose affinity is current."""
        if p.operation == IRQAffinityOperation.add:
            return current.union(p.cpus)
        remaining = current.intersection(p.cpus.negation())
        return remaining if remaining else p.cpus.negation()

    @classmethod
    def touches(cls, p):
        return {("irq", p.irq.number)}

    @classmethod
    def describe(cls, p, ctx):
        return cls.describe_many([p], ctx)

    @classmethod
    def describe_many(cls, ps, ctx):
        """One summary for all IRQs of a command; with -v also one line per changing IRQ."""
        from vfio_isolate import output
        from vfio_isolate.dryrun import unknown
        total = changing = dependent = 0
        seen = set()
        unreadable = {}  # reason -> count
        detail = []
        for p in ps:
            if not p.irq.exists():
                continue
            total += 1
            if p.irq.number in seen or ctx.depends(cls.reads(p)):
                dependent += 1  # an earlier step (or earlier in this batch) changes it
                continue
            seen.add(p.irq.number)
            try:
                old = p.irq.get_affinity()
            except OSError as e:
                reason = unknown(e)
                unreadable[reason] = unreadable.get(reason, 0) + 1
                continue
            new = cls._new_affinity(p, old)
            if new != old:
                changing += 1
                detail.append(f"  IRQ {p.irq.number}: {old.to_list_form()} -> {new.to_list_form()}")
        ops = {(p.operation, p.cpus.to_list_form()) for p in ps}
        how = ""
        if len(ops) == 1:
            op, cpus = next(iter(ops))
            how = f" ({op.name} {cpus})"
        line = f"change affinity of {changing} of {total} IRQ{'s' if total != 1 else ''}{how}"
        if unreadable:
            line += "; " + ", ".join(f"{n} {reason}" for reason, n in unreadable.items())
        if dependent:
            line += f"; {dependent} depend{'s' if dependent == 1 else ''} on earlier steps"
        return [line] + (detail if output.verbose_enabled else [])
