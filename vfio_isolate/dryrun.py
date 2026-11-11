"""State for `-n/--dry-run`: what earlier steps of the chain would change.

Existence of cpusets (created/deleted) and task counts are simulated, because they are exact.
Values (masks, governors, pools) are not: each action declares the resource keys it touches
and reads (Action.touches/reads); an action that reads a key an earlier step touched is
"dependent" and says so instead of showing a stale value from disk.

Only the dry-run executor builds a DryRunContext; the real path passes None and never reads it.
"""
import errno
from typing import Optional, Union

from vfio_isolate.cpuset import CPUSet

AFTER_EARLIER = "(after earlier steps)"
UNKNOWN_EARLIER = "unknown (depends on earlier steps)"
UNCHECKED_NOTE = "  (precondition checked only in a real run: depends on earlier steps)"


def norm(name: str) -> str:
    return "/" + "/".join(x for x in (name or "").split("/") if x)


def reason(e: OSError) -> str:
    if isinstance(e, FileNotFoundError) or e.errno == errno.ENOENT:
        return "does not exist"
    if isinstance(e, PermissionError) or e.errno in (errno.EACCES, errno.EPERM):
        return "permission denied"
    return e.strerror or str(e)


def unknown(e: OSError) -> str:
    return f"unknown ({reason(e)})"


def tasks_phrase(n) -> str:
    """"1 task", "3 tasks", or "unknown (...) tasks" for a count from DryRunContext.tasks."""
    return f"{n} task" if n == 1 else f"{n} tasks"


class DryRunContext:
    def __init__(self):
        self.created = set()   # cpusets an earlier step would create
        self.deleted = set()   # cpusets an earlier step would delete
        self.task_counts = {}  # name -> task count after earlier steps (int or "unknown (...)")
        self.task_touched = set()  # cpusets whose task count depends on earlier steps
        self.touched = set()   # resource keys earlier steps changed (Action.touches)
        self.unchecked = False  # the last can_execute skipped a check that depends on earlier steps
        # CPUs earlier steps put into isolated partitions, valid only while every earlier step
        # that changed the isolation is known exactly (see isolated_by_earlier)
        self.isolated_extra = set()
        self.isolation_exact = True
        self._isolation_noted = False
        self.partitions = {}   # name -> partition type an earlier step set (a created cpuset: member)

    def depends(self, keys) -> bool:
        return bool(set(keys) & self.touched)

    def is_new(self, name: str) -> bool:
        return norm(name) in self.created

    def exists(self, name: str, real_exists: bool) -> bool:
        n = norm(name)
        if n in self.created:
            return True
        if n in self.deleted:
            return False
        return real_exists

    def children(self, name: str, real_children) -> list:
        n = norm(name)
        result = {c for c in real_children if norm(c) not in self.deleted}
        result |= {c for c in self.created if c.rsplit("/", 1)[0] == (n if n != "/" else "")}
        return sorted(result)

    def tasks(self, name: str) -> Union[int, str]:
        """Number of tasks in the cpuset after the earlier steps, or "unknown (reason)"."""
        n = norm(name)
        if n in self.task_counts:
            return self.task_counts[n]
        try:
            return sum(1 for _ in CPUSet(n).pids())
        except OSError as e:
            return unknown(e)

    def depends_on_earlier(self, name: str) -> bool:
        return norm(name) in self.task_touched

    @staticmethod
    def _sum(a, b):
        return a + b if isinstance(a, int) and isinstance(b, int) else UNKNOWN_EARLIER

    # -- effects of steps -------------------------------------------------------------
    def create(self, name: str):
        n = norm(name)
        self.created.add(n)
        self.deleted.discard(n)
        self.task_counts[n] = 0
        self.task_touched.add(n)
        self.partitions[n] = "member"  # a new cpuset is no partition

    def delete(self, name: str):
        n = norm(name)
        parent = norm(n.rsplit("/", 1)[0])
        moved, there = self.tasks(n), self.tasks(parent)
        self.task_counts[parent] = self._sum(moved, there)
        self.task_touched.add(parent)
        self.created.discard(n)
        self.deleted.add(n)
        self.task_counts.pop(n, None)
        self.partitions.pop(n, None)

    def move(self, src: str, dst: str):
        s, d = norm(src), norm(dst)
        moved, there = self.tasks(s), self.tasks(d)
        self.task_counts[d] = self._sum(moved, there)
        self.task_counts[s] = 0
        self.task_touched.update((s, d))

    def move_recorded(self, src: str, dst: str):
        """Recorded PIDs move: which of them are still in src is not known beforehand."""
        s, d = norm(src), norm(dst)
        self.task_counts[s] = self.task_counts[d] = UNKNOWN_EARLIER
        self.task_touched.update((s, d))

    def note_isolated(self, cpus):
        """An overlay: this step makes exactly these CPUs isolated (partition valid)."""
        self.isolated_extra |= set(cpus)
        self._isolation_noted = True

    def partition_of(self, name: str) -> str:
        """The partition type of a cpuset after the earlier steps (disk value if none set it)."""
        n = norm(name)
        if n in self.partitions:
            return self.partitions[n]
        try:
            return CPUSet(n).get_partition()[0]
        except OSError:
            return "member"

    def has_partition_descendant(self, name: str) -> bool:
        """Does a cpuset below name (on disk or created/changed by earlier steps) have a root or
        isolated partition? Changing the parent's CPUs may then change what that partition owns."""
        n = norm(name)
        prefix = n.rstrip("/") + "/"
        if any(k.startswith(prefix) and v in ("root", "isolated") and k not in self.deleted
               for k, v in self.partitions.items()):
            return True
        todo = [n]
        while todo:
            try:
                kids = CPUSet(todo.pop()).children()
            except OSError:
                continue
            for kid in kids:
                if norm(kid) in self.deleted:
                    continue
                if self.partition_of(kid) in ("root", "isolated"):
                    return True
                todo.append(kid)
        return False

    def touch_isolation(self):
        """An earlier step changes the isolated CPUs in a way that is not modelled."""
        self.isolation_exact = False
        self.touched.add(("isolation",))

    def isolated_by_earlier(self):
        """The CPUs earlier steps isolated, or None if some step's effect on the isolation is not
        exactly known (a partition change without known CPUs, a delete, a restore step...)."""
        return set(self.isolated_extra) if self.isolation_exact else None

    def apply(self, action, p):
        """Record what the described step changes for the steps after it."""
        self._isolation_noted = False
        action.overlay(p, self)
        keys = action.touches(p)
        if ("isolation",) in keys and not self._isolation_noted:
            self.isolation_exact = False  # changes the isolation in a way not modelled
        self.touched |= keys


def cpuset_exists(name: str, ctx: Optional[DryRunContext]) -> bool:
    real = CPUSet(name).exists()
    return real if ctx is None else ctx.exists(name, real)
