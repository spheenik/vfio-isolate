from dataclasses import dataclass
from typing import Optional

from vfio_isolate import systemd
from vfio_isolate.cpuset import CPUNodeSet, NUMANodeSet, CPUSet
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
    def can_execute(cls, p: Param):
        if is_root(p.cpuset_name):
            raise PreconditionError("the root cgroup cannot be modified")
        if not CPUSet(p.cpuset_name).exists():
            raise PreconditionError(f"cpuset {p.cpuset_name} does not exist")
        unit = systemd.unit_for_cgroup(p.cpuset_name)
        if unit and p.partition is not None and not systemd.supports("CPUSetPartition"):
            raise PreconditionError(
                f"this systemd does not support CPUSetPartition=, cannot set a partition on {unit}")
        if (unit and p.partition in ("root", "isolated") and p.cpus is None
                and not systemd.show(unit, ["AllowedCPUs"])["AllowedCPUs"]):
            raise PreconditionError(
                f"--cpus is required with --partition {p.partition} on {unit}, "
                "which has no AllowedCPUs (systemd's CPUSetPartition= requires AllowedCPUs)")
        return True

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
