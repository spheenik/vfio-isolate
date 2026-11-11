from dataclasses import dataclass

from .action import Action, Execution
from ..cpu import CPU


class CPUGovernor(Action):
    name = "cpu-governor"
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

    batch = True

    @classmethod
    def touches(cls, p):
        return {("governor", p.cpu.number)}

    @classmethod
    def describe(cls, p, ctx):
        return cls.describe_many([p], ctx)

    @classmethod
    def describe_many(cls, ps, ctx):
        """Consecutive CPUs with the same old and new governor form one line."""
        from vfio_isolate.dryrun import unknown, AFTER_EARLIER
        from vfio_isolate.nodeset import CPUNodeSet
        runs = []  # [old, new, [cpu numbers]]
        seen = set()
        for p in sorted(ps, key=lambda x: x.cpu.number):  # stable: repeats keep their order
            if p.cpu.number in seen or ctx.depends(cls.reads(p)):
                old = AFTER_EARLIER  # an earlier step (or earlier in this batch) sets it
            else:
                try:
                    old = p.cpu.get_governor()
                except OSError as e:
                    old = unknown(e)
            seen.add(p.cpu.number)
            last = runs[-1] if runs else None
            if last and last[0] == old and last[1] == p.governor and last[2][-1] + 1 == p.cpu.number:
                last[2].append(p.cpu.number)
            else:
                runs.append([old, p.governor, [p.cpu.number]])
        return [f"set governor of CPU{'s' if len(cpus) > 1 else ''} {CPUNodeSet(set(cpus)).to_list_form()}: "
                f"{old} -> {new}" for old, new, cpus in runs]
