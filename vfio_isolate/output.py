import errno
import os
import sys

debug_enabled = False
verbose_enabled = False


def print_debug(*args, **kwargs):
    if debug_enabled:
        print(*args, **kwargs)


def print_verbose(*args, **kwargs):
    if verbose_enabled:
        print(*args, **kwargs)


def print_error(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


class FailureCollector:
    """Run-wide collector for per-item failures (IRQs, tasks) that must not stop the run."""

    # (item type, errno) -> (text for one item, text for several); {n} is the count.
    # These are expected and only summarized at the end.
    EXPECTED = {
        ("irq", errno.EIO): ("{n} IRQ is kernel-managed or not movable and kept its affinity",
                             "{n} IRQs are kernel-managed or not movable and kept their affinity"),
        ("irq", errno.ENOENT): ("{n} IRQ is gone", "{n} IRQs are gone"),
        ("task", errno.EINVAL): ("{n} task is a kernel thread and was not moved",
                                 "{n} tasks are kernel threads and were not moved"),
        ("task", errno.ESRCH): ("{n} task exited before it could be moved",
                                "{n} tasks exited before they could be moved"),
        ("kthread", errno.EINVAL): ("{n} per-CPU kernel thread cannot be moved",
                                    "{n} per-CPU kernel threads cannot be moved"),
        ("kthread", errno.ESRCH): ("{n} kernel thread exited before it could be moved",
                                   "{n} kernel threads exited before they could be moved"),
    }
    NOUN = {"irq": ("IRQ", "IRQs"), "task": ("task", "tasks"), "kthread": ("kernel thread", "kernel threads")}

    def __init__(self):
        self.reset()

    def reset(self):
        self.items = {}      # (kind, errno) -> [label, ...] in order of occurrence
        self.texts = {}      # (kind, errno) -> error text
        self.reported = set()  # unexpected (kind, errno) already printed immediately
        self.begin()

    def begin(self):
        """Start a per-execution scope (one command's attempts, successes, unexpected errors)."""
        self.scope_attempts = 0
        self.scope_ok = 0
        self.scope_unexpected = 0

    def end(self) -> bool:
        """True if the scope was a total failure: attempts, no success, an unexpected errno."""
        return self.scope_attempts > 0 and self.scope_ok == 0 and self.scope_unexpected > 0

    def ok(self):
        self.scope_attempts += 1
        self.scope_ok += 1

    def irq(self, number: int, err: OSError):
        self._add("irq", number, str(number), err)

    def task(self, pid: int, name: str, err: OSError):
        self._add("task", pid, f"{pid} ({name})", err)

    def kthread(self, pid: int, name: str, err: OSError):
        self._add("kthread", pid, f"{pid} ({name})", err)

    def _add(self, kind, ident, label, err):
        key = (kind, err.errno)
        self.scope_attempts += 1
        if key not in self.EXPECTED:
            self.scope_unexpected += 1
        self.items.setdefault(key, []).append(label)
        # errno-less OSErrors would print "Success" via strerror
        self.texts.setdefault(key, os.strerror(err.errno) if err.errno else str(err))
        if key not in self.EXPECTED and key not in self.reported:
            self.reported.add(key)
            what = {"irq": f"IRQ {ident}", "task": f"task {label}",
                    "kthread": f"kernel thread {label}"}[kind]
            print_error(f"vfio-isolate: warning: {what}: {self.texts[key]}")

    def report(self):
        for key, labels in self.items.items():
            kind, err = key
            single, plural = self.NOUN[kind]
            if key in self.EXPECTED:
                one, many = self.EXPECTED[key]
                line = "vfio-isolate: " + (one if len(labels) == 1 else many).format(n=len(labels))
            elif len(labels) > 1:
                line = (f"vfio-isolate: warning: ... and {len(labels) - 1} more {single if len(labels) == 2 else plural}: "
                        f"{self.texts[key]}")
            else:
                continue
            if verbose_enabled:
                shown = labels if key in self.EXPECTED else labels[1:]
                line += ": " + ", ".join(shown)
            print_error(line)


failures = FailureCollector()
