from dataclasses import dataclass

from vfio_isolate import systemd
from vfio_isolate.cpuset import CPUSet
from vfio_isolate.dryrun import cpuset_exists, norm
from .action import Action, Execution, PreconditionError


class CPUSetCreate(Action):
    name = "cpuset-create"
    needs_cgroup = True

    @dataclass
    class Param:
        cpuset_name: str

    @classmethod
    def can_execute(cls, p: Param, ctx=None):
        from .cpuset_modify import is_root
        if is_root(p.cpuset_name):
            raise PreconditionError("the root cgroup cannot be created")
        if systemd.unit_for_cgroup(p.cpuset_name):
            raise PreconditionError(f"cpuset {p.cpuset_name} is managed by systemd")
        parts = [x for x in p.cpuset_name.split("/") if x]
        for n in range(len(parts) - 1, 0, -1):
            ancestor = "/" + "/".join(parts[:n])
            unit = systemd.unit_for_cgroup(ancestor)
            if unit:
                if systemd.show(unit, ["Delegate"])["Delegate"] != "yes":
                    raise PreconditionError(
                        f"the parent {ancestor} is managed by systemd and does not delegate "
                        f"(Delegate=no); cannot create {p.cpuset_name}")
                break
        if cpuset_exists(p.cpuset_name, ctx):
            raise PreconditionError(f"cpuset {p.cpuset_name} already exists")
        return True

    @classmethod
    def touches(cls, p):
        return {("cpuset", norm(p.cpuset_name))}

    @classmethod
    def describe(cls, p, ctx):
        return [f"create cpuset {p.cpuset_name}"]

    @classmethod
    def overlay(cls, p, ctx):
        ctx.create(p.cpuset_name)

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        if cpu_set.exists():
            # undo of a delete that failed before rmdir
            return
        cpu_set.create()

    @classmethod
    def record_undo(cls, p):
        from .cpuset_delete import CPUSetDelete
        yield Execution(CPUSetDelete, CPUSetDelete.Param(cpuset_name=p.cpuset_name))
