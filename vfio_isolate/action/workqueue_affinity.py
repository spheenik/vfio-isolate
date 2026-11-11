import errno
from dataclasses import dataclass
from enum import Enum, unique

from vfio_isolate import workqueue
from vfio_isolate.nodeset import CPUNodeSet
from .action import Action, Execution, PreconditionError


@unique
class WorkqueueOperation(Enum):
    mask = 1
    add = 2
    restore = 3  # undo only: cpus is the previous requested mask


class WorkqueueAffinity(Action):
    name = "workqueue-affinity"

    @dataclass
    class Param:
        operation: WorkqueueOperation
        cpus: CPUNodeSet

    @staticmethod
    def _refusal(isolated: CPUNodeSet) -> PreconditionError:
        return PreconditionError(
            f"CPUs {isolated.to_list_form()} are in isolated cpuset partitions; the kernel already "
            f"keeps unbound workqueues off them. Run workqueue-affinity before creating the "
            f"partition, or leave it out")

    @classmethod
    def _target(cls, p: Param) -> CPUNodeSet:
        """The mask to write. mask/add refuse while CPUs are isolated (see the design); undo
        writes the previous mask minus the CPUs isolated now. Never leaves no online CPU."""
        isolated = workqueue.read_isolated()
        online = workqueue.read_online()
        if p.operation != WorkqueueOperation.restore and isolated:
            raise cls._refusal(isolated)
        if p.operation == WorkqueueOperation.mask:
            result = workqueue.read_requested().intersection(p.cpus.negation())
        elif p.operation == WorkqueueOperation.add:
            result = workqueue.read_requested().union(p.cpus)
        else:
            result = p.cpus.intersection(isolated.negation())
            if not result.intersection(online):
                result = online.intersection(isolated.negation())
        if not result.intersection(online):
            raise PreconditionError("no CPU would remain for unbound workqueues")
        return result

    @classmethod
    def touches(cls, p):
        return {("workqueue",)}

    @classmethod
    def reads(cls, p):
        return {("workqueue",), ("isolation",)}

    @classmethod
    def can_execute(cls, p: Param, ctx=None):
        if ctx is not None and ctx.depends(cls.reads(p)):
            extra = ctx.isolated_by_earlier()
            if p.operation != WorkqueueOperation.restore and extra:
                # an earlier step isolates known CPUs: the real run refuses exactly like this
                raise cls._refusal(workqueue.read_isolated().union(CPUNodeSet(extra)))
            ctx.unchecked = True  # the isolated CPUs and the mask depend on earlier steps
            return True
        cls._target(p)
        return True

    @classmethod
    def execute(cls, p: Param):
        target = cls._target(p)
        try:
            workqueue.write_cpumask(target)
        except OSError as e:
            if e.errno == errno.EOVERFLOW:
                raise PreconditionError(
                    f"workqueue mask {workqueue.format_mask(target)} names CPUs beyond the "
                    f"highest possible CPU") from e
            if e.errno == errno.EINVAL:
                raise PreconditionError(
                    f"the kernel rejected mask {workqueue.format_mask(target)}") from e
            raise

    @classmethod
    def record_undo(cls, p: Param):
        yield Execution(WorkqueueAffinity, WorkqueueAffinity.Param(
            operation=WorkqueueOperation.restore,
            cpus=workqueue.read_requested()))

    @classmethod
    def describe(cls, p, ctx):
        from vfio_isolate.dryrun import unknown, AFTER_EARLIER
        if ctx.depends(cls.reads(p)):
            cpus = p.cpus.to_list_form()
            how = {WorkqueueOperation.mask: f"the current mask without {cpus}",
                   WorkqueueOperation.add: f"the current mask plus {cpus}",
                   WorkqueueOperation.restore: f"{cpus} without isolated CPUs"}[p.operation]
            return [f"set unbound workqueue mask: {AFTER_EARLIER} -> {how}"]
        try:
            target = cls._target(p)
        except OSError as e:
            return [f"set unbound workqueue mask: {unknown(e)}"]
        try:
            old = workqueue.read_requested().to_list_form()
        except OSError as e:
            old = unknown(e)
        return [f"set unbound workqueue mask: {old} -> {target.to_list_form()}"]
