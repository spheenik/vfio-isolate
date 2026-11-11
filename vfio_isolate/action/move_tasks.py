from dataclasses import dataclass
from typing import List, Optional

from vfio_isolate.cpuset import CPUSet
from vfio_isolate.dryrun import cpuset_exists, norm, tasks_phrase
from .action import Action, Execution, PreconditionError


class MoveTasks(Action):
    name = "move-tasks"
    needs_cgroup = True

    @dataclass
    class Param:
        cpuset_from: str
        cpuset_to: str
        pids: Optional[List[int]] = None

    @classmethod
    def can_execute(cls, p: Param, ctx=None):
        for name in (p.cpuset_from, p.cpuset_to):
            if not cpuset_exists(name, ctx):
                raise PreconditionError(f"cpuset {name} does not exist")
        return True

    @classmethod
    def describe(cls, p: Param, ctx):
        route = f"from {p.cpuset_from} to {p.cpuset_to}"
        if p.pids is not None:
            n = len(p.pids)
            return [f"move {n} recorded task{'s' if n != 1 else ''} {route}"]
        n = ctx.tasks(p.cpuset_from)
        late = " (after earlier steps)" if ctx.depends_on_earlier(p.cpuset_from) else " (now)"
        if isinstance(n, str):
            return [f"move tasks {route} (task count {n})"]
        return [f"move {tasks_phrase(n)} {route}{late}"]

    @classmethod
    def touches(cls, p):
        # task counts are tracked by DryRunContext itself; no value any step reads changes
        return set()

    @classmethod
    def overlay(cls, p, ctx):
        if p.pids is None:
            ctx.move(p.cpuset_from, p.cpuset_to)
        else:
            ctx.move_recorded(p.cpuset_from, p.cpuset_to)

    @classmethod
    def execute(cls, p: Param):
        set_from = CPUSet(p.cpuset_from)
        set_to = CPUSet(p.cpuset_to)
        if p.pids is None:
            set_to.add_all_from_cpuset(set_from)
            return
        # only PIDs still in the source; the others exited or were moved elsewhere
        present = set(set_from.pids())
        for pid in p.pids:
            if pid in present:
                set_to.add_pid(pid, True)

    @classmethod
    def record_undo(cls, p):
        moved = list(CPUSet(p.cpuset_from).pids())
        yield Execution(MoveTasks, MoveTasks.Param(
            cpuset_from=p.cpuset_to, cpuset_to=p.cpuset_from, pids=moved))
