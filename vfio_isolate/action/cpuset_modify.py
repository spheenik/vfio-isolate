from dataclasses import dataclass
from typing import Optional

from vfio_isolate import systemd
from vfio_isolate.cpuset import CPUNodeSet, NUMANodeSet, CPUSet
from vfio_isolate.dryrun import cpuset_exists, unknown, norm, AFTER_EARLIER
from .action import Action, Execution, PreconditionError


def is_root(name: str) -> bool:
    return not [x for x in (name or "").split("/") if x]


class CPUSetModify(Action):
    name = "cpuset-modify"
    needs_cgroup = True

    @dataclass
    class Param:
        cpuset_name: str
        cpus: CPUNodeSet
        mems: NUMANodeSet
        partition: Optional[str] = None  # member/root/isolated; None = don't touch

    @classmethod
    def can_execute(cls, p: Param, ctx=None):
        if is_root(p.cpuset_name):
            raise PreconditionError("the root cgroup cannot be modified")
        if not cpuset_exists(p.cpuset_name, ctx):
            raise PreconditionError(f"cpuset {p.cpuset_name} does not exist")
        unit = systemd.unit_for_cgroup(p.cpuset_name)
        if unit and p.partition is not None and not systemd.supports("CPUSetPartition"):
            raise PreconditionError(
                f"this systemd does not support CPUSetPartition=, cannot set a partition on {unit}")
        if unit and p.partition in ("root", "isolated") and p.cpus is None:
            if ctx is not None and ctx.depends(cls.reads(p)):
                ctx.unchecked = True  # an earlier step may set AllowedCPUs
            elif not systemd.show(unit, ["AllowedCPUs"])["AllowedCPUs"]:
                raise PreconditionError(
                    f"--cpus is required with --partition {p.partition} on {unit}, "
                    "which has no AllowedCPUs (systemd's CPUSetPartition= requires AllowedCPUs)")
        return True

    @classmethod
    def touches(cls, p):
        keys = {("cpuset", norm(p.cpuset_name))}
        if p.partition is not None:
            keys.add(("isolation",))  # the kernel's isolated CPUs change
        elif p.cpus is not None:
            try:
                if CPUSet(p.cpuset_name).get_partition()[0] in ("root", "isolated"):
                    keys.add(("isolation",))  # new CPUs for a partition change what it isolates
            except OSError:
                pass
        return keys

    @classmethod
    def reads(cls, p):
        return {("cpuset", norm(p.cpuset_name))}

    @classmethod
    def overlay(cls, p, ctx):
        name = norm(p.cpuset_name)
        if ctx.partition_of(name) in ("root", "isolated"):
            ctx.isolation_exact = False  # it is a partition already (disk or earlier step): CPUs get replaced
        elif p.partition == "isolated" and p.cpus:
            ctx.note_isolated(p.cpus)  # the CPUs are known: the partition isolates exactly these
        if p.cpus is not None and ctx.has_partition_descendant(name):
            ctx.touch_isolation()  # new CPUs here may invalidate or shrink a partition below
        if p.partition is not None:
            ctx.partitions[name] = p.partition

    @classmethod
    def describe(cls, p: Param, ctx):
        """Current -> new values; read-only (systemctl show, cgroup files)."""
        name = p.cpuset_name
        new = ctx.is_new(name)
        later = not new and ctx.depends(cls.reads(p))  # an earlier step changes its values

        def current(read):
            if later:
                return AFTER_EARLIER
            if missing:
                return "does not exist"
            try:
                return read()
            except OSError as e:
                return unknown(e)

        def show(prop):
            return systemd.show(unit, [prop])[prop] or "(unset)"

        def lst(mask):
            return mask.to_list_form() if mask else "(inherit)"

        unit = None if new else systemd.unit_for_cgroup(name)
        cs = CPUSet(name)
        missing = not unit and not new and not cpuset_exists(name, ctx)
        lines = []
        where = f"unit {unit} (systemd)" if unit else f"cpuset {name}" + (" (new)" if new else "")

        def change(label, read, value):
            # a cpuset created earlier in the chain has no current value worth showing
            if new:
                return f"set {where}: {label} {value}"
            return f"set {where}: {label} {current(read)} -> {value}"

        if p.cpus is not None:
            if unit:
                lines.append(change("AllowedCPUs", lambda: show("AllowedCPUs"), p.cpus.to_list_form() or "(unset)"))
            else:
                lines.append(change("cpus", lambda: lst(cs.get_configured_cpus()), lst(p.cpus)))
        if p.mems is not None:
            if unit:
                lines.append(change("AllowedMemoryNodes", lambda: show("AllowedMemoryNodes"),
                                    p.mems.to_list_form() or "(unset)"))
            else:
                lines.append(change("mems", lambda: lst(cs.get_configured_mems()), lst(p.mems)))
        if p.partition is not None:
            if unit:
                lines.append(change("CPUSetPartition",
                                    lambda: systemd.show(unit, ["CPUSetPartition"])["CPUSetPartition"] or "member",
                                    p.partition))
            else:
                lines.append(change("partition", lambda: cs.get_partition()[0], p.partition))
        return lines or [f"leave {where} unchanged"]

    @classmethod
    def execute(cls, p: Param):
        cpu_set = CPUSet(p.cpuset_name)
        unit = systemd.unit_for_cgroup(p.cpuset_name)
        if unit:
            props = {}
            if p.cpus is not None:
                props["AllowedCPUs"] = p.cpus.to_list_form() if p.cpus else ""
            if p.mems is not None:
                props["AllowedMemoryNodes"] = p.mems.to_list_form() if p.mems else ""
            if p.partition is not None:
                props["CPUSetPartition"] = p.partition
            systemd.set_property(unit, **props)
            if p.partition is not None:
                cpu_set.verify_partition(p.partition)
            return

        if p.partition == "member":
            cpu_set.set_partition(p.partition)
        if p.cpus is not None:
            cpu_set.set_cpus(p.cpus)
        if p.mems is not None:
            cpu_set.set_mems(p.mems)
        if p.partition is not None and p.partition != "member":
            cpu_set.set_partition(p.partition)

    @classmethod
    def record_undo(cls, p):
        cpu_set = CPUSet(p.cpuset_name)
        cpus = mems = partition = None
        unit = systemd.unit_for_cgroup(p.cpuset_name)
        if unit:
            want = []
            if p.cpus is not None:
                want.append("AllowedCPUs")
            if p.mems is not None:
                want.append("AllowedMemoryNodes")
            if p.partition is not None:
                want.append("CPUSetPartition")
            values = systemd.show(unit, want) if want else {}
            if p.cpus is not None:
                cpus = CPUNodeSet(values["AllowedCPUs"])
            if p.mems is not None:
                mems = NUMANodeSet(values["AllowedMemoryNodes"])
            if p.partition is not None:
                # an unset property reads empty; restoring "empty" breaks the partition
                partition = values["CPUSetPartition"] or "member"
        else:
            if p.cpus is not None:
                cpus = cpu_set.get_configured_cpus()
            if p.mems is not None:
                mems = cpu_set.get_configured_mems()
            if p.partition is not None:
                partition = cpu_set.get_partition()[0]
        yield Execution(CPUSetModify, CPUSetModify.Param(
            cpuset_name=p.cpuset_name, cpus=cpus, mems=mems, partition=partition))
