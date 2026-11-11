from dataclasses import dataclass
from typing import Optional

from .action import Action, Execution, RolledBackError
from .. import hugepages


class HugePages(Action):
    name = "hugepages"

    @dataclass
    class Param:
        size_kb: int
        node: Optional[int]
        count: int
        release: bool = False

    @classmethod
    def execute(cls, p: Param):
        current = hugepages.read_count(p.size_kb, p.node)
        if p.release:
            # a read-back above the target is fine: the kernel keeps pages that are in use
            hugepages.write_count(p.size_kb, p.node, max(current - p.count, 0))
            return
        target = current + p.count
        size = hugepages.format_size(p.size_kb)
        where = f" on node N{p.node}" if p.node is not None else ""
        fmt = hugepages.format_size
        try:
            hugepages.write_count(p.size_kb, p.node, target)
            got = hugepages.read_count(p.size_kb, p.node)
        except OSError as err:
            try:
                hugepages.write_count(p.size_kb, p.node, current)
            except OSError:
                raise err  # pages may remain: the journal record must stay
            raise RolledBackError(f"could not add {fmt(p.count * p.size_kb)} in {size} pages{where}: {err}; "
                                  f"nothing was kept") from err
        if got < target:
            hugepages.write_count(p.size_kb, p.node, current)
            raise RolledBackError(
                f"got {fmt(max(got - current, 0) * p.size_kb)} of {fmt(p.count * p.size_kb)} "
                f"in {size} pages{where}; the pages were released")

    @classmethod
    def record_undo(cls, p: Param):
        if not p.release:
            yield Execution(HugePages, HugePages.Param(
                size_kb=p.size_kb, node=p.node, count=p.count, release=True))

    @classmethod
    def touches(cls, p):
        return {("hugepages", p.size_kb)}  # per size: node and system pools overlap

    @classmethod
    def describe(cls, p, ctx):
        from vfio_isolate.dryrun import unknown, AFTER_EARLIER
        fmt = hugepages.format_size
        if ctx.depends(cls.reads(p)):
            now = AFTER_EARLIER
        else:
            try:
                now = str(hugepages.read_count(p.size_kb, p.node))
            except OSError as e:
                now = unknown(e)
        amount = f"{fmt(p.count * p.size_kb)} in {fmt(p.size_kb)} pages ({p.count})"
        where = f"pool on node N{p.node}" if p.node is not None else "pool"
        if p.release:
            return [f"release {amount} from the {where}, now {now}"]
        return [f"add {amount} to the {where}, now {now}; "
                f"whether the kernel can supply them shows only in a real run"]
