"""The dry-run preview agrees with a real run, case by case, on the fake host.

Per case, on a fresh fake host: `-n` first (asserted not to change anything), then the same
command line for real on the same host. Because a preview leaves the host untouched, this is
equivalent to two identical hosts (fsroot.ROOT is a process global, so two cannot coexist).

  (a) the preview fails  =>  the real run fails, at the same command, with the same message
  (b) the preview succeeds without a "checked only in a real run" note  =>  the real run succeeds
  (c) every current value the preview prints without a marker ("(after earlier steps)", "unknown",
      "does not exist", "(new)") equals the value the real run found just before that step.

How (c) is checked without parsing free text for the real side: the real run's steps are
observed structurally, by wrapping each action's `execute` (reads the real old value from the
fake host's files right before the step; this is also what `record_undo` stores in the journal,
and for cpuset-modify / cpu-governor / workqueue-affinity it is cross-checked against the
recorded undo params). The preview side is observed by wrapping `describe` / `describe_many`
and reading the printed lines of exactly that step, so nothing in the product code is
instrumented.
"""
import os
import re
from pathlib import Path

import pytest

from readme_examples import extract
from vfio_isolate import journal, systemd
from vfio_isolate.action import ACTIONS
from vfio_isolate.cli import main
from vfio_isolate.cpuset import CPUSet
from vfio_isolate.dryrun import UNCHECKED_NOTE
from vfio_isolate.nodeset import CPUNodeSet

README = Path(__file__).resolve().parent.parent / "README.md"
MARKERS = ("(after earlier steps)", "unknown", "does not exist")
FAIL_RE = re.compile(r"^vfio-isolate: (?:dry run: )?([\w-]+) failed: (.*)$", re.M)


# --------------------------------------------------------------------------- hosts

def snapshot(root):
    snap = {}
    for dp, dns, fns in os.walk(root):
        for n in dns:
            snap[os.path.join(dp, n)] = None
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p) as f:
                snap[p] = (f.read(), os.stat(p).st_mtime_ns)
    return snap


def procs(host, name, pids):
    (host.root / "sys/fs/cgroup" / name.strip("/") / "cgroup.procs").write_text(
        "".join(f"{p}\n" for p in pids))


def seed_journal(host, path, steps):
    """Record real commands into a journal at path (setup of restore cases)."""
    for argv in steps:
        assert main(["-u", path] + argv) == 0
    lock = host.root / "run/vfio-isolate.lock"
    if lock.exists():
        lock.unlink()


def isolated_partition(host, name, cpus):
    d = host.mkcg(name, cpus=cpus)
    (d / "cpuset.cpus").write_text(cpus + "\n")
    (d / "cpuset.cpus.partition").write_text("isolated\n")


def s_none(host, tmp):
    pass


def s_a(host, tmp):
    host.mkcg("a")


def s_a_tasks(host, tmp):
    host.mkcg("a")
    procs(host, "/", [1, 2, 3])
    procs(host, "a", [7, 8])


def s_sys_irq(host, tmp):
    host.mkcg("system.slice")
    host.add_irq(41)


def s_ab(host, tmp):
    host.mkcg("a")
    host.mkcg("a/b")


def s_irqs(host, tmp):
    for n in (24, 25, 26):
        host.add_irq(n, "0-7")
    host.add_irq(27, "4-7")


def s_governors(host, tmp):
    for n in (3, 4):
        (host.root / f"sys/devices/system/cpu/cpu{n}/cpufreq/scaling_governor").write_text("schedutil\n")


def s_hugepages(host, tmp):
    host.set_hugepages(2048, 100)


def s_kthreads(host, tmp):
    host.add_kthread(2, "kthreadd", affinity="0-7")
    host.add_kthread(30, "kswapd0", affinity="0-7")
    host.add_kthread(31, "khugepaged", affinity="4-7")
    host.add_kthread(40, "ksoftirqd/1", affinity="1", percpu=True)
    host.add_process(500, "sshd", affinity="0-7")


def s_kthreads_isolated(host, tmp):
    s_kthreads(host, tmp)
    host.set_workqueue("0-7", isolated="4-7")
    host.mkcg("a")


def s_a_kthreads(host, tmp):
    s_kthreads(host, tmp)
    host.mkcg("a")


def s_kthread_journal(host, tmp):
    s_kthreads(host, tmp)
    seed_journal(host, str(tmp / "r.journal"), [["kthread-affinity", "mask", "C0-1"]])


def s_wq_isolated(host, tmp):
    host.set_workqueue("0-7", isolated="4-7")
    host.mkcg("a")


def s_machine_slice(host, tmp):
    sd = host.enable_systemd(units={"machine.slice": "/machine.slice"})
    sd.units["machine.slice"]["AllowedCPUs"] = "0-7"


def s_machine_slice_empty(host, tmp):
    host.enable_systemd(units={"machine.slice": "/machine.slice"})


def s_a_isolated(host, tmp):
    isolated_partition(host, "a", "4-7")


def s_a_isolated_child(host, tmp):
    host.mkcg("a")
    isolated_partition(host, "a/b", "4-7")


def s_a_and_journal_modify_delete(host, tmp):
    host.mkcg("a")
    seed_journal(host, str(tmp / "r.journal"), [["cpuset-modify", "--cpus", "C0-3", "/a"],
                                                 ["cpuset-delete", "/a"]])


def s_irq_journal(host, tmp):
    for n in (24, 25):
        host.add_irq(n, "0-7")
    seed_journal(host, str(tmp / "r.journal"), [["irq-affinity", "mask", "C0-3"],
                                                 ["irq-affinity", "mask", "C4-5"]])


def s_move_journal(host, tmp):
    host.mkcg("a")
    procs(host, "a", [7, 8])
    seed_journal(host, str(tmp / "r.journal"), [["move-tasks", "/a", "/"]])


def s_hugepages_journal(host, tmp):
    host.set_hugepages(2048, 100)
    seed_journal(host, str(tmp / "r.journal"), [["hugepages", "2M", "4M"]])


def s_modify_journal(host, tmp):
    host.mkcg("a")
    seed_journal(host, str(tmp / "r.journal"), [["cpuset-modify", "--cpus", "C0-3", "/a"]])


# (id, setup, argv); "{J}" in argv is the journal path seeded by the setup (restore cases)
CASES = [
    ("hook-line", s_sys_irq, ["cpuset-modify", "--cpus", "C0-7", "/system.slice", "irq-affinity", "mask", "C0-3"]),
    ("delete-missing", s_none, ["cpuset-delete", "/missing"]),
    ("stops-at-first-failure", s_a, ["cpuset-modify", "--cpus", "C0-1", "/a", "cpuset-delete", "/missing",
                                    "cpuset-modify", "--cpus", "C0-2", "/a"]),
    ("create-then-move", s_none, ["cpuset-create", "--cpus", "C0-7", "/a", "move-tasks", "/", "/a"]),
    ("move-counts-follow-chain", s_a_tasks, ["cpuset-create", "/b", "move-tasks", "/", "/b",
                                             "move-tasks", "/b", "/"]),
    ("create-existing", s_a, ["cpuset-create", "/a"]),
    ("delete-create-delete", s_a, ["cpuset-delete", "/a", "cpuset-create", "/a", "cpuset-delete", "/a"]),
    ("delete-then-move", s_a, ["cpuset-delete", "/a", "move-tasks", "/", "/a"]),
    ("delete-child-then-parent", s_ab, ["cpuset-delete", "/a/b", "cpuset-delete", "/a"]),
    ("create-child-blocks-delete", s_ab, ["cpuset-create", "/a/c", "cpuset-delete", "/a/b", "cpuset-delete", "/a"]),
    ("delete-with-tasks", s_a_tasks, ["cpuset-delete", "/a"]),
    ("governor-groups", s_governors, ["cpu-governor", "performance", "C0-5"]),
    ("governor-twice", s_none, ["cpu-governor", "performance", "C0-1", "cpu-governor", "powersave", "C1-2"]),
    ("irq-summary", s_irqs, ["-v", "irq-affinity", "mask", "C4-5"]),
    ("irq-add", s_irqs, ["-v", "irq-affinity", "add", "C0-7"]),
    ("irq-mask-then-add", s_irqs, ["-v", "irq-affinity", "mask", "C0-3", "irq-affinity", "add", "C0"]),
    ("irq-mask-then-add-changes", s_irqs, ["-v", "irq-affinity", "mask", "C4-7", "irq-affinity", "add", "C0"]),
    ("hugepages-add", s_hugepages, ["hugepages", "2M", "16G"]),
    ("hugepages-twice", s_hugepages, ["hugepages", "2M", "4M", "hugepages", "2M", "2M"]),
    ("workqueue-mask", s_none, ["workqueue-affinity", "mask", "C4-7"]),
    ("workqueue-refusal", s_wq_isolated, ["workqueue-affinity", "mask", "C0"]),
    ("workqueue-twice", s_none, ["workqueue-affinity", "mask", "C4-7", "workqueue-affinity", "add", "C6"]),
    ("kthread-summary", s_kthreads, ["-v", "kthread-affinity", "mask", "C4-5"]),
    ("kthread-add", s_kthreads, ["-v", "kthread-affinity", "add", "C0-7"]),
    ("kthread-twice", s_kthreads, ["-v", "kthread-affinity", "mask", "C4-5", "kthread-affinity", "add", "C0"]),
    ("kthread-refusal", s_kthreads_isolated, ["kthread-affinity", "mask", "C0"]),
    ("kthread-then-partition", s_a_kthreads,
     ["-v", "kthread-affinity", "mask", "C4-7", "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a"]),
    ("partition-then-kthread", s_a_kthreads,
     ["cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a", "kthread-affinity", "mask", "C4-7"]),
    ("partition-no-cpus-then-kthread", s_a_kthreads,
     ["cpuset-modify", "--partition", "isolated", "/a", "kthread-affinity", "mask", "C0"]),
    ("restore-kthread", s_kthread_journal, ["-v", "restore", "{J}"]),
    ("drop-compact", s_none, ["drop-caches", "compact-memory"]),
    ("modify-twice", s_a, ["cpuset-modify", "--cpus", "C0-3", "/a",
                           "cpuset-modify", "--cpus", "C0-1", "--mems", "N0", "/a"]),
    ("modify-twice-systemd", s_machine_slice_empty,
     ["cpuset-modify", "--cpus", "C0-3", "/machine.slice", "cpuset-modify", "--partition", "isolated",
      "/machine.slice"]),
    ("systemd-partition", s_machine_slice, ["cpuset-modify", "--cpus", "C0-3", "--partition", "isolated",
                                           "/machine.slice"]),
    ("partition-member-then-workqueue", s_wq_isolated,
     ["cpuset-modify", "--partition", "member", "/a", "workqueue-affinity", "mask", "C0"]),
    ("workqueue-then-partition", s_a, ["workqueue-affinity", "mask", "C4-7", "cpuset-modify", "--cpus", "C4-7",
                                      "--partition", "isolated", "/a"]),
    # partition (isolated, known CPUs) and then the workqueue: the preview must refuse like a real run
    ("partition-then-workqueue", s_a, ["cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a",
                                      "workqueue-affinity", "mask", "C4-7"]),
    ("create-partition-then-workqueue", s_none,
     ["cpuset-create", "/a", "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a",
      "workqueue-affinity", "add", "C0"]),
    ("create-partition-then-workqueue-mask", s_none,
     ["cpuset-create", "/a", "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a",
      "workqueue-affinity", "mask", "C4-7"]),
    ("create-partition-workqueue-first", s_none,
     ["workqueue-affinity", "mask", "C4-7", "cpuset-create", "--cpus", "C4-7", "/a",
      "cpuset-modify", "--partition", "isolated", "/a"]),
    ("systemd-partition-then-workqueue", s_machine_slice,
     ["cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/machine.slice",
      "workqueue-affinity", "mask", "C4-7"]),
    # not exactly knowable: CPUs come from the cpuset (never read for isolation), note stays
    ("partition-no-cpus-then-workqueue", s_a_isolated, ["cpuset-modify", "--partition", "isolated", "/a",
                                                         "workqueue-affinity", "mask", "C0"]),
    ("create-partition-delete-workqueue", s_none,
     ["cpuset-create", "/a", "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a",
      "cpuset-delete", "/a", "workqueue-affinity", "mask", "C4-7"]),
    ("partition-member-isolated-workqueue", s_a_isolated,
     ["cpuset-modify", "--partition", "member", "/a", "workqueue-affinity", "mask", "C0"]),
    ("partition-cpus-change-then-workqueue", s_a_isolated,
     ["cpuset-modify", "--cpus", "C4-5", "/a", "workqueue-affinity", "mask", "C0"]),
    ("delete-isolated-partition-then-workqueue", s_a_isolated,
     ["cpuset-delete", "/a", "workqueue-affinity", "mask", "C4-7"]),
    ("delete-isolated-partition-then-workqueue-add", s_a_isolated,
     ["cpuset-delete", "/a", "workqueue-affinity", "add", "C4-7"]),
    # changing the CPUs of a parent of a partition may change what the partition owns
    ("parent-cpus-of-partition-then-workqueue", s_a_isolated_child,
     ["cpuset-modify", "--cpus", "C0-7", "/a", "workqueue-affinity", "mask", "C0"]),
    ("parent-cpus-of-created-partition-then-workqueue", s_a,
     ["cpuset-create", "/a/b", "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a/b",
      "cpuset-modify", "--cpus", "C0-7", "/a", "workqueue-affinity", "mask", "C0"]),
    ("workqueue-with-existing-partition", s_a_isolated, ["workqueue-affinity", "mask", "C0"]),
    ("restore-modify-delete", s_a_and_journal_modify_delete, ["restore", "{J}"]),
    ("restore-irq", s_irq_journal, ["-v", "restore", "{J}"]),
    ("restore-move-then-move", s_move_journal, ["restore", "{J}", "move-tasks", "/", "/a"]),
    ("restore-hugepages", s_hugepages_journal, ["restore", "{J}"]),
    ("restore-then-modify", s_modify_journal, ["restore", "{J}", "cpuset-modify", "--cpus", "C0-1", "/a"]),
]


# minimum number of compared values per case; a string says why there is nothing to compare
EXPECTED_COMPARED = {
    "hook-line": 1,
    "delete-missing": "the preview refuses at the first command; no step runs",
    "stops-at-first-failure": 1,
    "create-then-move": 1,
    "move-counts-follow-chain": 1,
    "create-existing": "the preview refuses at the first command; no step runs",
    "delete-create-delete": 1,
    "delete-then-move": 1,
    "delete-child-then-parent": 1,
    "create-child-blocks-delete": 1,
    "delete-with-tasks": 1,
    "governor-groups": 6,
    "governor-twice": 3,
    "irq-summary": 4,
    "irq-add": 1,
    "irq-mask-then-add-changes": 3,
    "irq-mask-then-add": 3,
    "hugepages-add": 1,
    "hugepages-twice": 1,
    "workqueue-mask": 1,
    "workqueue-refusal": "the preview refuses; no value is printed",
    "workqueue-twice": 1,
    "kthread-summary": 3,
    "kthread-add": 1,
    "kthread-twice": 3,
    "kthread-refusal": "the preview refuses; no value is printed",
    "kthread-then-partition": 3,
    "partition-then-kthread": 2,  # the cpuset-modify values; the kthread-affinity step refuses
    "partition-no-cpus-then-kthread": 1,  # the cpuset-modify value; the kthread step depends on the partition
    "restore-kthread": 2,
    "drop-compact": "drop-caches and compact-memory have no current value",
    "modify-twice": 1,
    "modify-twice-systemd": 1,
    "systemd-partition": 2,
    "partition-member-then-workqueue": 1,
    "workqueue-then-partition": 3,
    "partition-then-workqueue": 2,
    "create-partition-then-workqueue": "the cpuset is new (no current value) and the workqueue step refuses",
    "create-partition-then-workqueue-mask": "the cpuset is new (no current value) and the workqueue step refuses",
    "create-partition-workqueue-first": 1,
    "systemd-partition-then-workqueue": 2,
    "partition-no-cpus-then-workqueue": 1,
    "create-partition-delete-workqueue": "the cpuset is new (no current value); the workqueue value is after earlier steps",
    "partition-member-isolated-workqueue": 1,
    "partition-cpus-change-then-workqueue": 1,
    "delete-isolated-partition-then-workqueue": 1,
    "delete-isolated-partition-then-workqueue-add": 1,
    "parent-cpus-of-partition-then-workqueue": 1,
    "parent-cpus-of-created-partition-then-workqueue": 1,
    "workqueue-with-existing-partition": "the preview refuses; no value is printed",
    "restore-modify-delete": "the restore recreates a deleted cpuset: its values are new or after earlier steps",
    "restore-irq": 2,
    "restore-move-then-move": "every task count is after earlier steps",
    "restore-hugepages": 1,
    "restore-then-modify": 1,
}


COMPARABLE = {"cpuset-modify", "cpu-governor", "irq-affinity", "hugepages", "workqueue-affinity",
              "cpuset-delete", "move-tasks", "kthread-affinity"}


def readme_expected(argv):
    """An example that touches existing values (or restores the journal seeded by readme_setup,
    which holds a cpuset-modify and an irq-affinity) must have something compared; one that only
    creates cpusets or drops caches has no current value to compare."""
    names = COMPARABLE & set(argv)
    if "add" in argv:
        names.discard("irq-affinity")  # every IRQ of the example host already has those CPUs
        names.discard("kthread-affinity")  # so does every kernel thread
    return 1 if names or "restore" in argv else 0


def readme_setup(host, tmp, argv):
    """The fake host the README examples run on (as in test_readme_dry_run), fresh per example."""
    host.enable_systemd(units={"system.slice": "/system.slice", "user.slice": "/user.slice",
                               "init.scope": "/init.scope", "machine.slice": "/machine.slice"})
    for cg in ("host", "vm"):
        host.mkcg(cg, cpus="0-31")
    for n in (24, 25, 41):
        host.add_irq(n, "0-31")
    host.add_kthread(2, "kthreadd", affinity="0-31")
    host.add_kthread(30, "kswapd0", affinity="0-31")
    host.add_kthread(40, "ksoftirqd/1", affinity="1", percpu=True)
    creates = "cpuset-create" in argv and "/vfio-test" in argv
    if not creates:
        host.mkcg("vfio-test", cpus="0-31")
    if "restore" in argv:
        (host.root / "sys/fs/cgroup/host/cpuset.cpus").write_text("0-31\n")
        seed_journal(host, str(tmp / "r.journal"), [["cpuset-modify", "--cpus", "C0-15", "/host"],
                                                     ["irq-affinity", "mask", "C0-3"]])
        assert len(journal.read_journal(str(tmp / "r.journal"))) >= 2


def readme_cases():
    cases = []
    for no, argv in extract(README.read_text()):
        assert not any("$" in a for a in argv), f"README.md:{no}: unsubstituted variable in {argv}"
        cases.append(pytest.param(argv, id=f"readme-{no}"))
    assert len(cases) >= 5
    return cases


# --------------------------------------------------------------------------- observation

class Recorder:
    """Wraps describe/describe_many (preview) and execute (real run) of every action."""

    def __init__(self, host, monkeypatch):
        self.host = host
        self.dry = []      # (name, lines, items, noted) per describe call, in order: items is the
        #                    number of executions the call covers, noted whether the step carried
        #                    the "checked only in a real run" note
        self.real = []     # (name, pre-state of the host, params) per execute call
        self.undo = {}     # id(params) -> recorded undo steps
        for name, cls in ACTIONS.items():
            self._wrap(monkeypatch, cls, "describe_many" if cls.batch else "describe")
            self._wrap_execute(monkeypatch, cls)
            self._wrap_undo(monkeypatch, cls)

    def _wrap(self, monkeypatch, cls, attr):
        orig = getattr(cls, attr)
        dry = self.dry

        def wrapper(c, *args):
            lines = orig(*args)
            batch = attr == "describe_many"
            dry.append((cls.name, list(lines), len(args[0]) if batch else 1, bool(args[-1].unchecked)))
            return lines
        monkeypatch.setattr(cls, attr, classmethod(wrapper))

    def _wrap_execute(self, monkeypatch, cls):
        orig = cls.execute
        real = self.real

        def wrapper(c, p):
            real.append((cls.name, read_old(self.host, cls.name, p), p))
            return orig(p)
        monkeypatch.setattr(cls, "execute", classmethod(wrapper))

    def _wrap_undo(self, monkeypatch, cls):
        orig = cls.record_undo
        undo = self.undo

        def wrapper(c, p):
            steps = list(orig(p))
            undo[id(p)] = steps
            return iter(steps)
        monkeypatch.setattr(cls, "record_undo", classmethod(wrapper))


def cgdir(host, name):
    return host.root / host.cgroup_mount.lstrip("/") / name.strip("/")


def read_old(host, name, p):
    """The real current values, straight from the fake host's files (None: not readable)."""
    try:
        return OLD_READERS[name](host, p)
    except (OSError, KeyError):
        return None


def _cpus_text(text):
    text = text.strip()
    return CPUNodeSet(text).to_list_form() if text else "(inherit)"


def _old_modify(host, p):
    unit = systemd.unit_for_cgroup(p.cpuset_name)
    old = {}
    if unit:
        u = host.systemd.units[unit]
        for label in ("AllowedCPUs", "AllowedMemoryNodes"):
            old[label] = u[label].replace(",", " ") or "(unset)"
        old["CPUSetPartition"] = u["CPUSetPartition"] or "member"
    else:
        d = cgdir(host, p.cpuset_name)
        old["cpus"] = _cpus_text((d / "cpuset.cpus").read_text())
        old["mems"] = _cpus_text((d / "cpuset.mems").read_text())
        old["partition"] = (d / "cpuset.cpus.partition").read_text().split()[0]
    return old


def _old_governor(host, p):
    return (host.root / f"sys/devices/system/cpu/cpu{p.cpu.number}/cpufreq/scaling_governor").read_text().strip()


def _old_irq(host, p):
    return _cpus_text((host.root / f"proc/irq/{p.irq.number}/smp_affinity_list").read_text())


def _old_hugepages(host, p):
    base = ("sys/kernel/mm" if p.node is None else f"sys/devices/system/node/node{p.node}")
    return int((host.root / base / f"hugepages/hugepages-{p.size_kb}kB/nr_hugepages").read_text())


def _old_kthread(host, p):
    return host.thread_affinity(p.pid)


def _old_workqueue(host, p):
    return host.workqueue_mask("cpumask_requested").to_list_form()


def _old_tasks(host, name):
    return len([l for l in (cgdir(host, name) / "cgroup.procs").read_text().split() if l])


OLD_READERS = {
    "cpuset-modify": _old_modify,
    "cpu-governor": _old_governor,
    "irq-affinity": _old_irq,
    "hugepages": _old_hugepages,
    "workqueue-affinity": _old_workqueue,
    "kthread-affinity": _old_kthread,
    "cpuset-delete": lambda host, p: _old_tasks(host, p.cpuset_name),
    "move-tasks": lambda host, p: None if p.pids is not None else _old_tasks(host, p.cpuset_from),
}


# --------------------------------------------------------------------------- comparison

def marked(value):
    return value.startswith(MARKERS)


def unmarked_pairs(name, lines):
    """[(key, printed current value)] of the values a preview prints for one step.

    key: what the real side is looked up by (label, CPU number, IRQ number, ...)."""
    pairs = []
    for line in lines:
        line = line.strip()
        if name == "cpuset-modify":
            m = re.match(r"set (?:unit \S+ \(systemd\)|cpuset \S+): (\w+) (.+?) -> ", line)
            if m:
                pairs.append((m.group(1), m.group(2)))
        elif name == "cpu-governor":
            m = re.match(r"set governor of CPUs? (\S+): (.+?) -> ", line)
            if m:
                pairs += [(cpu, m.group(2)) for cpu in CPUNodeSet(m.group(1))]
        elif name == "irq-affinity":
            m = re.match(r"IRQ (\d+): (\S+) ->(?: |$)", line)
            if m:
                pairs.append((int(m.group(1)), m.group(2)))
        elif name == "hugepages":
            m = re.search(r", now (\S+?)(?:;|$)", line)
            if m:
                pairs.append(("now", m.group(1)))
        elif name == "kthread-affinity":
            m = re.match(r"(\d+) .+: (\S+) -> ", line)
            if m:
                pairs.append((int(m.group(1)), m.group(2)))
        elif name == "workqueue-affinity":
            m = re.match(r"set unbound workqueue mask: (.+?) -> ", line)
            if m:
                pairs.append(("mask", m.group(1)))
        elif name == "cpuset-delete":
            m = re.match(r"delete cpuset \S+; its (\S+) tasks? moves? to \S+( \(after earlier steps\))?$", line)
            if m:
                pairs.append(("tasks", "(after earlier steps)" if m.group(2) else m.group(1)))
        elif name == "move-tasks":
            m = re.match(r"move (\d+) tasks? from \S+ to \S+ \((now|after earlier steps)\)$", line)
            if m:
                pairs.append(("tasks", m.group(1) if m.group(2) == "now" else "(after earlier steps)"))
    return [(k, v) for k, v in pairs if not marked(v)]


def real_value(name, pre, key):
    if pre is None:
        return None
    if name == "cpuset-modify":
        return pre.get(key)
    if name in ("cpu-governor", "irq-affinity", "kthread-affinity"):
        return pre
    if name == "hugepages":
        return str(pre)
    if name in ("workqueue-affinity", "cpuset-delete", "move-tasks"):
        return str(pre)
    return None


def compare_values(rec):
    """Compare unmarked preview values with the real ones; returns the number compared.

    The k-th preview call of an action is the k-th step of that action in the real run. A
    batch action's call covers the next `items` real executions (one command's group); each
    item is compared with the value on disk right before the step, i.e. its first execution
    within that group (later ones of the same item are marked in the preview)."""
    compared = 0
    for name in {c[0] for c in rec.dry}:
        calls = [c for c in rec.dry if c[0] == name]
        real = [(pre, p) for n, pre, p in rec.real if n == name]
        pos = 0
        for _, lines, items, _ in calls:
            chunk = real[pos:pos + items]
            pos += items
            if name in ("cpu-governor", "irq-affinity", "kthread-affinity"):
                first = {}
                for pre, p in chunk:
                    first.setdefault({"cpu-governor": lambda p: p.cpu.number, "irq-affinity": lambda p: p.irq.number,
                                      "kthread-affinity": lambda p: p.pid}[name](p), pre)
                for key, value in unmarked_pairs(name, lines):
                    if first.get(key) is None:
                        continue
                    assert value == first[key], (
                        f"{name} {key}: preview {value!r}, real {first[key]!r} ({lines})")
                    compared += 1
                continue
            for pre, p in chunk:
                for key, value in unmarked_pairs(name, lines):
                    want = real_value(name, pre, key)
                    if want is None:
                        continue
                    assert value == want, f"{name} {key}: preview {value!r}, real {want!r} ({lines})"
                    compared += 1
    return compared


def cross_check_undo(rec):
    """The old values read from the host are the ones record_undo wrote to the journal."""
    for name, pre, p in rec.real:
        steps = rec.undo.get(id(p))
        if not steps or pre is None:
            continue
        s = steps[0].params
        if name == "cpu-governor":
            assert s.governor == pre
        elif name == "kthread-affinity":
            assert s.cpus.to_list_form() == pre
        elif name == "workqueue-affinity":
            assert s.cpus.to_list_form() == pre
        elif name == "cpuset-modify":
            if s.cpus is not None and not systemd.unit_for_cgroup(p.cpuset_name):
                assert (s.cpus.to_list_form() if s.cpus else "(inherit)") == pre["cpus"]
            if s.partition is not None and not systemd.unit_for_cgroup(p.cpuset_name):
                assert s.partition == pre["partition"]


# --------------------------------------------------------------------------- the test

def fail_of(err):
    m = FAIL_RE.search(err)
    # a real run appends a restore hint the preview has no use for
    return (m.group(1), re.sub(r'; run "vfio-isolate restore .*$', "", m.group(2))) if m else None


def agree(host, tmp, argv, capsys, monkeypatch):
    rec = Recorder(host, monkeypatch)
    uses_journal = "restore" not in argv
    ja, jb = str(tmp / "ja"), str(tmp / "jb")
    argv = [a.replace("{J}", str(tmp / "r.journal")) for a in argv]
    pre_args = ["-u", "{}"] if uses_journal else []
    if uses_journal and any(a in ("-u", "--undo-file") for a in argv):
        i = next(i for i, a in enumerate(argv) if a in ("-u", "--undo-file"))
        del argv[i:i + 2]

    def with_journal(path):
        return ([pre_args[0], path] if pre_args else []) + argv

    before = snapshot(host.root)
    rc_dry = main(["-n"] + with_journal(ja))
    dry = capsys.readouterr()
    assert snapshot(host.root) == before, "the preview changed the host"
    assert not os.path.exists(ja), "the preview created a journal"
    rc_real = main(with_journal(jb))
    real = capsys.readouterr()

    if rc_dry != 0:                                              # (a)
        assert rc_real != 0, f"preview failed but the real run passed: {dry.err}"
        assert fail_of(dry.err) == fail_of(real.err), f"dry: {dry.err!r}\nreal: {real.err!r}"
    elif "checked only in a real run" not in dry.out:            # (b)
        assert rc_real == 0, f"preview passed cleanly but the real run failed: {real.err}"
    elif rc_real != 0:
        # the note is a promise that only that step is unchecked: a real failure must be there
        noted = {c[0] for c in rec.dry if c[3]}
        failed = fail_of(real.err)
        assert failed is not None and failed[0] in noted, (
            f"preview noted {sorted(noted)} but the real run failed elsewhere: {real.err!r}\n{dry.out}")
    cross_check_undo(rec)
    n = compare_values(rec)
    return n, rc_dry, rc_real, dry, real


@pytest.mark.parametrize("name,setup,argv", CASES, ids=[c[0] for c in CASES])
def test_chain_agrees(fake_host, tmp_path, capsys, monkeypatch, name, setup, argv):
    host = fake_host
    host.patch_cgroup_fs()
    setup(host, tmp_path)
    capsys.readouterr()
    want = EXPECTED_COMPARED[name]  # every case states what it compares
    n = agree(host, tmp_path, argv, capsys, monkeypatch)[0]
    if isinstance(want, int):
        assert n >= want, f"{name}: compared {n} values, expected at least {want}"
    else:
        assert n == 0, f"{name}: compared {n} values although '{want}'"


@pytest.mark.parametrize("argv", readme_cases())
def test_readme_invocation_agrees(fake_host_factory, tmp_path, capsys, monkeypatch, argv):
    host = fake_host_factory(num_cpus=32, governors="performance powersave")
    host.patch_cgroup_fs()
    readme_setup(host, tmp_path, argv)
    capsys.readouterr()
    argv = [a for a in argv if a != "-n"]  # the comparison runs the same line once with -n, once without
    if "restore" in argv:
        argv = argv[:-1] + [str(tmp_path / "r.journal")]  # restore [-n] FILE: the journal seeded above
    # -v: IRQ values are only printed per IRQ with it
    n = agree(host, tmp_path, ["-v"] + list(argv), capsys, monkeypatch)[0]
    assert n >= readme_expected(argv), f"{argv}: compared {n} values"


# --------------------------------------------------------------------------- the new refusal

def test_partition_then_workqueue_refuses_like_a_real_run(fake_host, tmp_path, capsys, monkeypatch):
    host = fake_host
    host.patch_cgroup_fs()
    host.mkcg("a")
    argv = ["cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a",
            "workqueue-affinity", "mask", "C4-7"]
    _, rc_dry, rc_real, dry, real = agree(host, tmp_path, argv, capsys, monkeypatch)
    assert rc_dry == rc_real == 1
    assert fail_of(dry.err)[0] == "workqueue-affinity"
    assert "CPUs 4-7 are in isolated cpuset partitions" in dry.err
    assert UNCHECKED_NOTE not in dry.out


def test_delete_isolated_partition_then_workqueue_is_a_note_and_passes(fake_host, tmp_path, capsys, monkeypatch):
    host = fake_host
    host.patch_cgroup_fs()
    isolated_partition(host, "a", "4-7")
    capsys.readouterr()
    _, rc_dry, rc_real, dry, real = agree(
        host, tmp_path, ["cpuset-delete", "/a", "workqueue-affinity", "mask", "C4-7"], capsys, monkeypatch)
    assert rc_dry == rc_real == 0
    assert UNCHECKED_NOTE in dry.out


def test_checker_detects_a_wrong_preview_value():
    # unmarked values are compared; markers are skipped
    assert unmarked_pairs("cpu-governor", ["set governor of CPUs 0-1: powersave -> performance"]) == [
        (0, "powersave"), (1, "powersave")]
    assert unmarked_pairs("cpu-governor", ["set governor of CPU 1: (after earlier steps) -> x"]) == []
    assert unmarked_pairs("cpuset-modify", ["set cpuset /a: cpus unknown (permission denied) -> 0-1"]) == []

    class Rec:
        dry = [("workqueue-affinity", ["set unbound workqueue mask: 0-3 -> 0-1"], 1, False)]
        real = [("workqueue-affinity", CPUNodeSet("0-7").to_list_form(), None)]
    with pytest.raises(AssertionError):
        compare_values(Rec)


def test_created_partition_then_workqueue_refuses_exactly(fake_host, tmp_path, capsys, monkeypatch):
    # the cpuset was created by an earlier step (a member): its partition is still exactly known
    host = fake_host
    host.patch_cgroup_fs()
    argv = ["cpuset-create", "/a", "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a",
            "workqueue-affinity", "mask", "C0"]
    _, rc_dry, rc_real, dry, real = agree(host, tmp_path, argv, capsys, monkeypatch)
    assert rc_dry == rc_real == 1
    assert fail_of(dry.err)[0] == "workqueue-affinity"
    assert "CPUs 4-7 are in isolated cpuset partitions" in dry.err
    assert UNCHECKED_NOTE not in dry.out


@pytest.mark.parametrize("setup,argv", [
    (s_a_isolated_child, ["cpuset-modify", "--cpus", "C0-7", "/a", "workqueue-affinity", "mask", "C0"]),
    (s_a, ["cpuset-create", "/a/b", "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a/b",
           "cpuset-modify", "--cpus", "C0-7", "/a", "workqueue-affinity", "mask", "C0"]),
], ids=["on-disk", "by-earlier-step"])
def test_parent_cpus_of_a_partition_make_isolation_inexact(fake_host, tmp_path, capsys, monkeypatch, setup, argv):
    host = fake_host
    host.patch_cgroup_fs()
    setup(host, tmp_path)
    capsys.readouterr()
    rc = main(["-n"] + argv)
    out = capsys.readouterr().out
    assert rc == 0
    assert UNCHECKED_NOTE in out  # not an exact verdict about the workqueue step
