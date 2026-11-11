import errno
from dataclasses import dataclass
from enum import Enum, unique
from typing import Optional

from vfio_isolate import kthread, output, workqueue
from vfio_isolate.nodeset import CPUNodeSet
from .action import Action, Execution, PreconditionError


@unique
class KThreadOperation(Enum):
    mask = 1
    add = 2
    restore = 3  # undo only: cpus is the previous affinity of the thread


class KThreadAffinity(Action):
    name = "kthread-affinity"

    @dataclass
    class Param:
        operation: KThreadOperation
        pid: int
        cpus: CPUNodeSet
        # restore only (None for mask/add): which thread the PID belonged to when it was recorded.
        # comm is for messages; it is not compared because workers rename themselves.
        starttime: Optional[int]
        comm: Optional[str]

    batch = True

    @staticmethod
    def _refusal(isolated: CPUNodeSet) -> PreconditionError:
        return PreconditionError(
            f"CPUs {isolated.to_list_form()} are in isolated cpuset partitions; the kernel already "
            f"keeps kernel threads off them. Run kthread-affinity before creating the "
            f"partition, or leave it out")

    @classmethod
    def _new_affinity(cls, p: Param, current: CPUNodeSet) -> CPUNodeSet:
        """What execute writes for a thread whose affinity is current."""
        if p.operation == KThreadOperation.restore:
            return p.cpus
        if p.operation == KThreadOperation.add:
            return current.union(p.cpus)
        remaining = current.intersection(p.cpus.negation())
        return remaining if remaining else cls._online_but(p.cpus)  # none left: online CPUs but the masked

    @staticmethod
    def _online_but(cpus: CPUNodeSet) -> CPUNodeSet:
        return workqueue.read_online().intersection(cpus.negation())

    @classmethod
    def touches(cls, p):
        return {("kthread", p.pid)}

    @classmethod
    def reads(cls, p):
        if p.operation == KThreadOperation.restore:
            return cls.touches(p)
        return cls.touches(p) | {("isolation",)}

    @classmethod
    def can_execute(cls, p: Param, ctx=None):
        if p.operation == KThreadOperation.restore:
            return True
        if ctx is not None and ctx.depends({("isolation",)}):
            extra = ctx.isolated_by_earlier()
            if extra:
                # an earlier step isolates known CPUs: the real run refuses exactly like this
                raise cls._refusal(workqueue.read_isolated().union(CPUNodeSet(extra)))
            ctx.unchecked = True  # the isolated CPUs depend on earlier steps
            return True
        isolated = workqueue.read_isolated()
        if isolated:
            raise cls._refusal(isolated)
        if p.operation == KThreadOperation.mask and not cls._online_but(p.cpus):
            raise PreconditionError("no CPU would remain for kernel threads")
        return True

    @classmethod
    def execute(cls, p: Param):
        restoring = p.operation == KThreadOperation.restore
        if restoring and not cls._same_thread(p):
            # exited, and the PID may belong to something else by now: leave it alone
            output.failures.kthread(p.pid, p.comm or "?", ProcessLookupError(errno.ESRCH, "No such process"))
            return
        try:
            new = cls._new_affinity(p, kthread.get_affinity(p.pid))
            kthread.set_affinity(p.pid, new)
        except OSError as e:
            if restoring and e.errno not in (errno.ESRCH, errno.EINVAL):
                raise  # an unexpected failure keeps the step in the journal
            output.failures.kthread(p.pid, kthread.comm(p.pid), e)
            return
        output.failures.ok()

    @staticmethod
    def _same_thread(p: Param) -> bool:
        """Is p.pid still the kernel thread that was recorded (PID reuse)?"""
        try:
            _, flags, starttime = kthread.read_stat(p.pid)
        except (OSError, ValueError, IndexError):
            return False
        return bool(flags & kthread.PF_KTHREAD) and starttime == p.starttime

    @classmethod
    def record_undo(cls, p: Param):
        if p.operation == KThreadOperation.restore:
            return
        try:
            old = kthread.get_affinity(p.pid)
            name, _, starttime = kthread.read_stat(p.pid)
        except (OSError, ValueError, IndexError):
            return  # gone (or unreadable): nothing to restore, execute reports it
        yield Execution(KThreadAffinity, KThreadAffinity.Param(
            operation=KThreadOperation.restore, pid=p.pid, cpus=old, starttime=starttime, comm=name))

    @classmethod
    def describe(cls, p, ctx):
        return cls.describe_many([p], ctx)

    @classmethod
    def describe_many(cls, ps, ctx):
        """One summary for all kernel threads of a command; with -v one line per changing thread."""
        from vfio_isolate.dryrun import unknown
        total = changing = dependent = gone = 0  # without kthreadd, which the line names itself
        kthreadd = False
        unreadable = {}  # reason -> count
        detail = []
        for p in ps:
            is_kthreadd = p.pid == kthread.KTHREADD_PID
            if ctx.depends(cls.reads(p)):
                dependent += 1  # an earlier step changes it, or the isolated CPUs
                total += not is_kthreadd
                kthreadd |= is_kthreadd
                continue
            try:
                old = kthread.get_affinity(p.pid)
            except ProcessLookupError:
                gone += 1
                continue
            except OSError as e:
                reason = unknown(e)
                unreadable[reason] = unreadable.get(reason, 0) + 1
                continue
            kthreadd |= is_kthreadd
            total += not is_kthreadd
            new = cls._new_affinity(p, old)
            if new != old:
                changing += not is_kthreadd
                detail.append(f"  {p.pid} {kthread.comm(p.pid)}: {old.to_list_form()} -> {new.to_list_form()}")
        ops = {(p.operation, p.cpus.to_list_form()) for p in ps}
        if len(ops) == 1 and next(iter(ops))[0] != KThreadOperation.restore:
            op, cpus = next(iter(ops))
            how = f": {op.name} {cpus}"
        else:
            how = ""
        verb = "restore" if all(p.operation == KThreadOperation.restore for p in ps) else "set"
        if kthreadd and not total:
            line = f"{verb} affinity of kthreadd{how}"
        else:
            who = "kthreadd and " if kthreadd else ""
            line = f"{verb} affinity of {who}{changing} of {total} kernel thread{'s' if total != 1 else ''}{how}"
        if unreadable:
            line += "; " + ", ".join(f"{n} {reason}" for reason, n in unreadable.items())
        if gone:
            line += f"; {gone} gone"
        if dependent:
            line += f"; {dependent} depend{'s' if dependent == 1 else ''} on earlier steps"
        note = "  (threads that refuse are only known in a real run)"
        return [line, note] + (detail if output.verbose_enabled else [])
