import errno
import time
from dataclasses import dataclass

from vfio_isolate import systemd
from vfio_isolate.cpuset import CPUSet
from vfio_isolate.dryrun import cpuset_exists, norm, tasks_phrase
from .action import Action, Execution, PreconditionError

REMOVE_TIMEOUT = 2.0
REMOVE_INTERVAL = 0.05


class CPUSetDelete(Action):
    name = "cpuset-delete"
    needs_cgroup = True

    @dataclass
    class Param:
        cpuset_name: str

    @classmethod
    def can_execute(cls, p: Param, ctx=None):
        from .cpuset_modify import is_root
        if is_root(p.cpuset_name):
            raise PreconditionError("the root cgroup cannot be deleted")
        if systemd.unit_for_cgroup(p.cpuset_name):
            raise PreconditionError(f"cpuset {p.cpuset_name} is managed by systemd")
        if not cpuset_exists(p.cpuset_name, ctx):
            raise PreconditionError(f"cpuset {p.cpuset_name} does not exist")
        cls._refuse_children(CPUSet(p.cpuset_name), ctx)
        return True

    @staticmethod
    def _refuse_children(cpu_set: CPUSet, ctx=None):
        children = cpu_set.children() if cpu_set.exists() else []
        if ctx is not None:
            children = ctx.children(cpu_set.name(), children)
        if children:
            raise PreconditionError(
                f"cpuset {cpu_set.name()} has child cgroups: {', '.join(children)}")

    @classmethod
    def describe(cls, p: Param, ctx):
        n = ctx.tasks(p.cpuset_name)
        parent = CPUSet(p.cpuset_name).parent().name()
        late = " (after earlier steps)" if ctx.depends_on_earlier(p.cpuset_name) else ""
        verb = "moves" if n == 1 else "move"
        return [f"delete cpuset {p.cpuset_name}; its {tasks_phrase(n)} {verb} to {parent}{late}"]

    @classmethod
    def touches(cls, p):
        keys = {("cpuset", norm(p.cpuset_name))}
        try:
            if CPUSet(p.cpuset_name).get_partition()[0] in ("root", "isolated"):
                keys.add(("isolation",))  # deleting a partition frees its CPUs
        except OSError:
            pass  # not on disk (created by an earlier step): that step touched isolation itself
        return keys

    @classmethod
    def overlay(cls, p, ctx):
        if ctx.partition_of(p.cpuset_name) in ("root", "isolated"):
            ctx.isolation_exact = False  # deleting a partition frees its CPUs
        ctx.delete(p.cpuset_name)

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        if not cpu_set.exists():
            # undo of a create that failed before mkdir
            return
        # a task may still be exiting or migrating: retry only EBUSY, only briefly
        deadline = time.monotonic() + REMOVE_TIMEOUT
        first = True
        while True:
            # report task move failures on the first pass only: retries would count them again
            cpu_set.parent().add_all_from_cpuset(cpu_set, report=first)
            first = False
            try:
                cpu_set.remove()
                return
            except OSError as e:
                if e.errno != errno.EBUSY:
                    raise
                # EBUSY is also what live child cgroups cause (restore skips can_execute)
                cls._refuse_children(cpu_set)
            if time.monotonic() >= deadline:
                raise PreconditionError(f"cpuset {p.cpuset_name} is still in use")
            time.sleep(REMOVE_INTERVAL)

    @classmethod
    def record_undo(cls, p):
        from .cpuset_create import CPUSetCreate
        from .cpuset_modify import CPUSetModify

        yield Execution(CPUSetCreate, CPUSetCreate.Param(
            cpuset_name=p.cpuset_name
        ))

        cpu_set = CPUSet(p.cpuset_name)
        yield Execution(CPUSetModify, CPUSetModify.Param(
            cpuset_name=p.cpuset_name,
            cpus=cpu_set.get_configured_cpus(),
            mems=cpu_set.get_configured_mems(),
            partition=cpu_set.get_partition()[0]
        ))
