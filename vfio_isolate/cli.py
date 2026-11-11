import fcntl
import json
import os
import sys
from dataclasses import dataclass, is_dataclass

import click

from vfio_isolate.action import *
from vfio_isolate import cpuset, fsroot, hugepages, journal, kthread, output, privileges
from vfio_isolate.privileges import NotRootError
from vfio_isolate.systemd import SystemctlError
from vfio_isolate.cpu import CPU
from vfio_isolate.cpuset import HostUnsupportedError, PartitionInvalidError
from vfio_isolate import irq as irq_module
from vfio_isolate.irq import IRQS
from vfio_isolate.journal import JournalError
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet, NodeSet, NodeSetSyntaxError
from vfio_isolate.serialize import *


def _parse_nodeset(cls, text, value):
    try:
        s = cls(text)
    except NodeSetSyntaxError as e:
        raise click.BadParameter(f"{value!r}: {e}")
    if not s:
        raise click.BadParameter(f"{value!r}: the set is empty")
    return s


def _check_exists(s, value, what):
    missing = [n for n in sorted(s) if not CPUNodeSet({n}).is_valid()] if what == "CPUs" \
        else [n for n in sorted(s) if not NUMANodeSet({n}).is_valid()]
    if missing:
        raise click.BadParameter(f"{value!r}: {what} {NodeSet(set(missing)).to_list_form()} do not exist")


def cb_numa_nodeset(ctx, param, value):
    if not value:
        return None
    if value[0] != 'N':
        raise click.BadParameter(f"{value!r}: must start with N")
    s = _parse_nodeset(NUMANodeSet, value[1:], value)
    _check_exists(s, value, "NUMA nodes")
    return s


def cb_cpu_nodeset(ctx, param, value):
    if not value:
        return None
    if value[0] == 'N':
        s = cb_numa_nodeset(ctx, param, value).get_cpu_nodeset()
        if not s:
            raise click.BadParameter(f"{value!r}: the NUMA nodes have no CPUs")
        return s
    elif value[0] == 'C':
        s = _parse_nodeset(CPUNodeSet, value[1:], value)
    elif value[0] == 'M':
        if len(value) == 1:
            raise click.BadParameter(f"{value!r}: the set is empty")
        try:
            s = CPUNodeSet.from_mask(value[1:])
        except NodeSetSyntaxError as e:
            raise click.BadParameter(f"{value!r}: {e}")
        if not s:
            raise click.BadParameter(f"{value!r}: the set is empty")
    else:
        raise click.BadParameter(f"{value!r}: must start with C, N or M")
    _check_exists(s, value, "CPUs")
    return s


class EnumChoice(click.Choice):
    def __init__(self, enum, case_sensitive=False, use_value=False):
        self.enum = enum
        self.use_value = use_value
        choices = [str(e.value) if use_value else e.name for e in self.enum]
        super().__init__(choices, case_sensitive)

    def convert(self, value, param, ctx):
        result = super().convert(value, param, ctx)
        # Find the original case in the enum
        if not self.case_sensitive and result not in self.choices:
            result = next(c for c in self.choices if result.lower() == c.lower())
        if self.use_value:
            return next(e for e in self.enum if str(e.value) == result)
        return self.enum[result]


CPUS_HELP = ("C<list>: CPUs, e.g. C0-3,8. N<list>: all CPUs of the given NUMA nodes, e.g. N0. "
             "M<mask>: hex CPU mask as in /proc/irq/*/smp_affinity, e.g. M3c or Mff,0000000f.")
CPUS_DOC = "\b\nCPUS is one of:\n  " + "\n  ".join([
    "C<list>  CPUs, e.g. C0-3,8",
    "N<list>  all CPUs of the given NUMA nodes, e.g. N0",
    "M<mask>  hex CPU mask as in /proc/irq/*/smp_affinity, e.g. M3c, Mff,0000000f",
])
MEMS_HELP = "N<list>: NUMA memory nodes, e.g. N0 or N0-1."


@click.group(chain=True)
@click.option('-v', '--verbose', help="enable verbose output", is_flag=True)
@click.option('-d', '--debug', help="enable debug output", is_flag=True)
@click.option('-n', '--dry-run', 'dry_run', is_flag=True,
              help="Check the preconditions and print what each command would do; change nothing "
                   "(no root needed where the files involved are readable).")
@click.option('-u', '--undo-file', metavar="<undo-file>",
              help="Record the undo steps of each command in this file before the command runs "
                   "(appended to if the file exists). Undo with: vfio-isolate restore <undo-file>")
@click.pass_obj
def cli(executor, verbose, debug, dry_run, undo_file):
    """Isolate CPUs and memory for VFIO VMs.

    Commands can be chained; they run in the order given, and all arguments are
    validated before anything runs. Every run with a command (including restore) needs root.

    \b
    Exit status:
      0    success
      1    failure, including a command that changed nothing because of
           unexpected errors
      2    usage error
      130  interrupted
    """
    from vfio_isolate import output
    output.verbose_enabled = verbose
    output.debug_enabled = debug
    executor.undo_file = undo_file
    executor.dry_run = dry_run


@cli.command('drop-caches')
@click.pass_obj
def drop_caches(executor, **args):
    """drop caches"""
    executor.add(DropCaches, args)


@cli.command('compact-memory')
@click.pass_obj
def compact_memory(executor, **args):
    """compact memory"""
    executor.add(CompactMemory, args)


@cli.command('cpuset-create')
@click.argument("cpuset-name", metavar="<cpuset-name>")
@click.option("--cpus", metavar="<cpus>", help="Set the CPUs used by the cpuset. " + CPUS_HELP,
              callback=cb_cpu_nodeset)
@click.option("--mems", metavar="<nodes>", help="Set the NUMA memory nodes used by the cpuset. " + MEMS_HELP,
              callback=cb_numa_nodeset)
@click.pass_obj
def cpuset_create(executor, **args):
    """create a cpuset

    The new cpuset inherits its parent's CPUs and memory nodes unless --cpus/--mems
    are given. Refused for systemd units and /.
    """
    executor.add(CPUSetCreate, args)
    executor.add(CPUSetModify, args)


@cli.command('cpuset-modify')
@click.argument("cpuset-name", metavar="<cpuset-name>")
@click.option("--cpus", metavar="<cpus>", help="Set the CPUs used by the cpuset. " + CPUS_HELP,
              callback=cb_cpu_nodeset)
@click.option("--mems", metavar="<nodes>", help="Set the NUMA memory nodes used by the cpuset. " + MEMS_HELP,
              callback=cb_numa_nodeset)
@click.option("--partition", type=click.Choice(["member", "root", "isolated"]),
              help="EXPERIMENTAL: set the cgroup v2 partition type of the cpuset. On systemd units, "
                   "root/isolated need --cpus unless the unit already has AllowedCPUs. "
                   "Undo restores the previous partition type.")
@click.pass_obj
def cpuset_modify(executor, **args):
    """modify a cpuset

    Systemd units are changed via systemctl set-property --runtime, other cgroups
    by direct writes.
    """
    executor.add(CPUSetModify, args)


@cli.command('cpuset-delete')
@click.argument("cpuset-name", metavar="<cpuset-name>")
@click.pass_obj
def cpuset_delete(executor, **args):
    """delete a cpuset

    Its tasks move to the parent cpuset. Refused for systemd units and /.
    """
    executor.add(CPUSetDelete, args)


@cli.command('move-tasks')
@click.argument("cpuset-from", metavar="<cpuset-from>")
@click.argument("cpuset-to", metavar="<cpuset-to>")
@click.pass_obj
def move_tasks(executor, **args):
    """move all tasks from one cpuset to another

    Kernel threads and tasks that exited meanwhile are skipped and summarized.
    """
    executor.add(MoveTasks, args)


@cli.command('irq-affinity', help="""manipulate the IRQ affinity of all active IRQs

\b
irq-affinity mask CPUS  remove the CPUs from each IRQ's affinity; if none
                        would remain, the IRQ gets all other CPUs
irq-affinity add CPUS   add the CPUs to each IRQ's affinity

""" + CPUS_DOC)
@click.argument("operation", type=EnumChoice(IRQAffinityOperation))
@click.argument("cpus", metavar="<cpus>", callback=cb_cpu_nodeset)
@click.pass_obj
def irq_affinity(executor, **args):
    if irq_module.irqbalance_running():
        click.echo(irq_module.IRQBALANCE_WARNING, err=True)
    group = object()  # all IRQs of this command form one failure scope
    for irq in IRQS.active():
        executor.add(IRQAffinity, IRQAffinity.Param(
            irq=irq,
            operation=args["operation"],
            cpus=args["cpus"]
        ), group=group)


@cli.command('workqueue-affinity', help="""restrict the CPUs of unbound kernel workqueues

\b
workqueue-affinity mask CPUS  remove the CPUs from the unbound workqueue mask
workqueue-affinity add CPUS   add the CPUs to the unbound workqueue mask

CPUs in isolated cpuset partitions are never written (the kernel already keeps
workqueues off them). A result without any CPU is refused.

""" + CPUS_DOC)
@click.argument("operation", type=click.Choice(["mask", "add"], case_sensitive=False))
@click.argument("cpus", metavar="<cpus>", callback=cb_cpu_nodeset)
@click.pass_obj
def workqueue_affinity(executor, **args):
    executor.add(WorkqueueAffinity, WorkqueueAffinity.Param(
        operation=WorkqueueOperation[args["operation"].lower()],
        cpus=args["cpus"]
    ))


@cli.command('kthread-affinity', help="""keep kernel threads off CPUs

\b
kthread-affinity mask CPUS  remove the CPUs from the affinity of kthreadd and of
                            every kernel thread that accepts it; if none would
                            remain, the thread gets all other CPUs
kthread-affinity add CPUS   add the CPUs to their affinity

Kernel threads stay in the root cgroup, so cpusets cannot keep them off the VM's
CPUs. kthreadd (PID 2) creates all kernel threads and they inherit its affinity,
so threads started later are restricted too. Per-CPU kernel threads refuse a new
affinity and are skipped. Undo restores each thread's previous
affinity. Refused while CPUs are in isolated cpuset partitions (the kernel then
keeps kernel threads off them itself); run it before creating the partition.

""" + CPUS_DOC)
@click.argument("operation", type=click.Choice(["mask", "add"], case_sensitive=False))
@click.argument("cpus", metavar="<cpus>", callback=cb_cpu_nodeset)
@click.pass_obj
def kthread_affinity(executor, **args):
    group = object()  # all kernel threads of this command form one failure scope
    for t in kthread.list_kernel_threads():  # kthreadd first
        executor.add(KThreadAffinity, KThreadAffinity.Param(
            operation=KThreadOperation[args["operation"].lower()],
            pid=t.pid,
            cpus=args["cpus"],
            starttime=None,
            comm=None
        ), group=group)


@cli.command('cpu-governor', help="""set the CPU governor for the given CPUs

The governor is checked against each CPU's available governors before anything runs.
A governor module that is not loaded is refused; load it first (modprobe cpufreq_<name>).

""" + CPUS_DOC)
@click.argument("governor")
@click.argument("cpus", metavar="<cpus>", callback=cb_cpu_nodeset)
@click.pass_obj
def cpu_governor(executor, **args):
    """set the CPU governor for the given CPUs"""
    governor = args["governor"]
    available = {}
    for n in sorted(args["cpus"]):
        try:
            available[n] = CPU(n).get_available_governors()
        except OSError:
            available[n] = None
    no_cpufreq = [n for n, g in available.items() if g is None]
    unsupported = [n for n, g in available.items() if g is not None and governor not in g]
    if no_cpufreq or unsupported:
        union = sorted({x for g in available.values() if g for x in g})
        problems = []
        if no_cpufreq:
            problems.append(f"CPUs {CPUNodeSet(set(no_cpufreq)).to_list_form()} have no cpufreq")
        if unsupported:
            problems.append(f"CPUs {CPUNodeSet(set(unsupported)).to_list_form()} "
                            f"do not support governor {governor!r}")
        raise click.BadParameter(
            "; ".join(problems) + f"; available governors: {' '.join(union) or '(none)'}",
            param_hint="governor")
    group = object()
    for n in args["cpus"]:
        cpu = CPU(n)
        executor.add(CPUGovernor, CPUGovernor.Param(
            cpu=cpu,
            governor=args["governor"]
        ), group=group)


def cb_hugepage_size(ctx, param, value):
    sizes = hugepages.available_sizes()
    offered = " ".join(hugepages.format_size(s) for s in sizes) or "(none)"
    try:
        size = hugepages.parse_size(value)
    except ValueError as e:
        raise click.BadParameter(str(e))
    if size not in sizes:
        raise click.BadParameter(f"{value!r} is not an available page size; available: {offered}")
    return size


def cb_hugepage_amount(ctx, param, value):
    try:
        return hugepages.parse_size(value)
    except ValueError as e:
        raise click.BadParameter(str(e))


def cb_single_numa_node(ctx, param, value):
    if value is None:
        return None
    if not value or value[0] != 'N':
        raise click.BadParameter(f"{value!r}: --node takes a NUMA node written with N, e.g. N0")
    nodes = sorted(cb_numa_nodeset(ctx, param, value))
    if len(nodes) != 1:
        raise click.BadParameter(f"{value!r}: --node takes exactly one node, e.g. N0")
    return nodes[0]


@cli.command('hugepages', help="""add pages to the hugepage pool

Usage: hugepages [--node N<n>] <pagesize> <amount>  (options before the arguments)

Raises the pool of <pagesize> pages by <amount> of memory, system-wide or on one NUMA
node. Both are <n>K, <n>M or <n>G; <pagesize> must be one the kernel offers and
<amount> an exact multiple of it. The page size must match the one the VM uses
(libvirt: <page size=...> in <memoryBacking>).

Examples: hugepages 2M 16G, hugepages 1G 16G, hugepages --node N0 1G 8G

The undo releases the added pages again (never below zero), whatever else changed the
pool meanwhile; pages still in use are freed when their user exits. If the kernel
provides fewer pages than asked, the command fails, releases the pages it got and
leaves no undo record.

""")
@click.argument("pagesize", metavar="<pagesize>", callback=cb_hugepage_size)
@click.argument("amount", metavar="<amount>", callback=cb_hugepage_amount)
@click.option("--node", metavar="N<n>", callback=cb_single_numa_node,
              help="NUMA node to add the pages to, e.g. N0 (default: system-wide)")
@click.pass_obj
def hugepages_cmd(executor, pagesize, amount, node):
    size = hugepages.format_size(pagesize)
    if amount % pagesize:
        raise click.BadParameter(f"{hugepages.format_size(amount)} is not a multiple of {size}",
                                 param_hint="<amount>")
    if node is not None and not os.path.isdir(hugepages.pool_dir(pagesize, node)):
        have = [n for n in sorted(NUMANodeSet.online_nodes())
                if os.path.isdir(hugepages.pool_dir(pagesize, n))]
        raise click.BadParameter(f"NUMA node N{node} has no {size} hugepage pool; "
                                 f"nodes with one: {' '.join(f'N{n}' for n in have) or '(none)'}",
                                 param_hint="--node")
    executor.add(HugePages, HugePages.Param(
        size_kb=pagesize, node=node, count=amount // pagesize))


@cli.command('restore')
@click.option('-n', '--dry-run', 'dry_run', is_flag=True,
              help="Print what the restore would do; change nothing (same as the global -n; "
                   "give it before <undo-file>).")
@click.argument("undo-file", metavar="<undo-file>")
@click.pass_obj
def restore(executor, dry_run, undo_file):
    """restore a previous state using an undo file

    Undoes all recorded runs, newest first. The file is deleted on success; on
    failures only the failed steps are kept and the exit status is 1, so restore
    can be retried. Cannot be combined with -u.
    """
    if executor.undo_file:
        raise click.UsageError("-u/--undo-file cannot be combined with restore")
    if dry_run:
        executor.dry_run = True
    if not executor.dry_run:
        privileges.require_root()
    # read and decode now, so a bad file stops the whole chain before anything runs
    records = journal.read_journal(undo_file)
    st = os.stat(undo_file)
    key = (st.st_dev, st.st_ino)
    if key in executor.restore_ids:
        raise click.UsageError(f"undo file {undo_file} given to restore more than once")
    executor.restore_ids.add(key)
    executor.add_restore(RestoreBatch(undo_file, records))


@dataclass
class RestoreBatch:
    path: str
    records: list  # list[list[Execution]], in file order (oldest first)


class Executor:
    def __init__(self):
        self.executions = []  # Execution or RestoreBatch
        self.undo_file = None
        self.dry_run = False
        self.restore_ids = set()  # (st_dev, st_ino) of journals already queued for restore
        self.restore_path = None  # undo file of the restore batch being replayed, if any
        self.current = None   # name of the action being checked/recorded/executed, or "restore"
        self.changed = False  # an action's execute (or a restore batch) has started
        self.records = 0      # journal records appended this run
        self.groups = {}      # id(Execution) -> group token of the command that queued it

    def add(self, action_class, params, group=None):
        """Queue an action. Executions sharing a group (one click command) share a failure scope."""
        if not is_dataclass(params):
            params = unserialize(action_class.Param, params)
        e = Execution(action=action_class, params=params)
        self.groups[id(e)] = group if group is not None else object()
        self.executions.append(e)

    def add_restore(self, batch):
        self.executions.append(batch)

    def _needs_cgroup(self):
        for e in self.executions:
            steps = [s for r in e.records for s in r] if isinstance(e, RestoreBatch) else [e]
            if any(s.action.needs_cgroup for s in steps):
                return True
        return False

    def run_dry(self) -> int:
        """Preview: check preconditions and print what each action would do; change nothing.

        No root check, lock, journal or execute, and no record_undo (describe reads current
        values itself, read-only)."""
        from vfio_isolate.dryrun import DryRunContext, UNCHECKED_NOTE
        journal_status = None
        if self._needs_cgroup():
            cpuset.cgroup_root()
        if self.undo_file:
            # a real run fails on a bad journal before changing anything: so does the preview
            journal_status = journal.check_for_append(self.undo_file)
        ctx = DryRunContext()
        announced = False

        pending = []  # (action, params) of a batch action, described together
        pending_group = None

        def flush():
            if pending:
                action = pending[0][0]
                for line in action.describe_many([p for _, p in pending], ctx):
                    print(line if line.startswith(" ") else f"would {line}")
                if ctx.unchecked:
                    print(UNCHECKED_NOTE)
                    ctx.unchecked = False
                for _, p in pending:
                    ctx.apply(action, p)
                pending.clear()

        def show(action, params, group=None):
            nonlocal pending_group
            if pending and not (action is pending[0][0] and group is pending_group):
                flush()
            if action.batch:
                pending.append((action, params))
                pending_group = group
                return
            for line in action.describe(params, ctx):
                print(f"would {line}")
            if ctx.unchecked:
                print(UNCHECKED_NOTE)
                ctx.unchecked = False
            ctx.apply(action, params)

        for e in self.executions:
            if isinstance(e, RestoreBatch):
                flush()
                self.current = "restore"
                print(f"would restore {e.path} ({len(e.records)} "
                      f"record{'s' if len(e.records) != 1 else ''}, newest first)")
                for record in reversed(e.records):
                    group = object()  # a record is one batch scope: records never merge
                    for step in record:
                        show(step.action, step.params, group)
                flush()
                continue
            if pending and not (e.action is pending[0][0] and self.groups.get(id(e)) is pending_group):
                flush()
            self.current = e.action.name
            ctx.unchecked = False
            if e.action.can_execute(e.params, ctx) is False:
                raise PreconditionError(f"{e.action.name}: precondition failed")
            if self.undo_file and not announced:
                if journal_status == "unreadable":
                    print(f"would record undo in {self.undo_file} (existing journal not readable "
                          f"as this user; checked only in a real run)")
                else:
                    print(f"would record undo in {self.undo_file}")
                if journal_status == "truncated":
                    print(f"would drop truncated last line of {self.undo_file}")
                announced = True
            show(e.action, e.params, self.groups.get(id(e)))
        flush()
        return 0

    def run(self) -> int:
        if self.dry_run:
            return self.run_dry()
        privileges.require_root()
        # one run at a time (also restore): concurrent hooks must not interleave
        lock_fd = os.open(fsroot.path("/run/vfio-isolate.lock"),
                          os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            return self._run()
        finally:
            os.close(lock_fd)

    def _run(self) -> int:
        # fail before touching anything (record_undo reads cgroup files too)
        if self._needs_cgroup():
            cpuset.cgroup_root()
        appender = journal.open_for_append(self.undo_file) if self.undo_file else None
        rc = 0
        scope = None  # group token of the open failure scope, if any

        def close_scope():
            nonlocal scope, rc
            if scope is not None:
                scope = None
                label = self._scope_label
                if output.failures.end():
                    print(f"vfio-isolate: {label[0]}: no {label[1]} could be {label[2]}", file=sys.stderr)
                    rc = max(rc, 1)

        try:
            for e in self.executions:
                group = None if isinstance(e, RestoreBatch) else self.groups.get(id(e))
                if scope is not None and group is not scope:
                    close_scope()
                if (group is not None and scope is None
                        and e.action in (IRQAffinity, MoveTasks, KThreadAffinity)):
                    scope = group
                    self._scope_label = {IRQAffinity: (e.action.name, "IRQ", "changed"),
                                         MoveTasks: (e.action.name, "task", "moved"),
                                         KThreadAffinity: (e.action.name, "kernel thread", "changed")
                                         }[e.action]
                    output.failures.begin()
                if isinstance(e, RestoreBatch):
                    self.current = "restore"
                    self.restore_path = e.path
                    self.changed = True
                    rc = max(rc, self._restore(e))
                    self.restore_path = None
                    continue
                self.current = e.action.name
                if e.action.can_execute(e.params) is False:
                    raise PreconditionError(f"{e.action.name}: precondition failed")
                steps = list(e.action.record_undo(e.params))
                if appender:
                    appender.append(steps)
                    self.records += bool(steps)
                changed_before = self.changed
                self.changed = True
                try:
                    e.action.execute(e.params)
                except RolledBackError:
                    if appender and steps:
                        appender.discard_last()
                        self.records -= 1
                    self.changed = changed_before
                    raise
            close_scope()
        finally:
            if appender:
                appender.close()
        return rc

    @staticmethod
    def _restore(batch) -> int:
        # the journal may have changed since parse time (another run holding the lock
        # appended, or another restore finished): use what is on disk now
        try:
            records = journal.read_journal(batch.path)
        except JournalError:
            if not os.path.lexists(batch.path):
                print(f"restore: {batch.path}: already restored", file=sys.stderr)
                return 0
            raise
        failed_records = []
        # newest record first, steps within a record in recorded order
        for record in reversed(records):
            failed = []
            for step in record:
                try:
                    step.action.execute(step.params)
                except Exception as ex:
                    try:
                        params = json.dumps(journal.encode(step)["params"])
                    except Exception:
                        params = repr(step.params)
                    print(f"restore: {step.action.name} {params}: {ex}", file=sys.stderr)
                    failed.append(step)
            if failed:
                failed_records.append(failed)
        try:
            if not failed_records:
                os.unlink(batch.path)
                return 0
            failed_records.reverse()  # back to file order
            journal.rewrite(batch.path, failed_records)
        except (OSError, JournalError) as ex:
            print(f"vfio-isolate: could not update journal {batch.path}: {ex} "
                  f"(journal left as it was)", file=sys.stderr)
            return 1
        return 1


def _hint(executor):
    if executor.dry_run:
        return None
    if executor.undo_file and executor.records:
        return f'run "vfio-isolate restore {executor.undo_file}" to undo the changes made so far'
    if not executor.undo_file and executor.changed:
        return "changes made before the failure remain"
    return None


def _say(executor, message, *extra):
    parts = [message, *extra]
    hint = _hint(executor)
    if hint:
        parts.append(hint)
    marker = "dry run: " if executor.dry_run else ""
    print("vfio-isolate: " + marker + "; ".join(parts), file=sys.stderr)


def _interrupted(executor):
    if not executor.changed:
        print("vfio-isolate: interrupted, nothing was changed", file=sys.stderr)
    elif executor.current == "restore" and executor.restore_path:
        print(f"vfio-isolate: interrupted during restore of {executor.restore_path}; "
              f"it was left unchanged, run restore again", file=sys.stderr)
    else:
        _say(executor, f"interrupted during {executor.current}")
    return 130


def main(argv=None) -> int:
    from vfio_isolate import output
    output.failures.reset()
    executor = Executor()
    try:
        rv = cli.main(args=argv, prog_name="vfio-isolate", standalone_mode=False, obj=executor)
        if isinstance(rv, int):
            return rv
        return executor.run()
    except click.exceptions.Exit as e:
        return e.exit_code
    except (click.exceptions.Abort, KeyboardInterrupt):
        return _interrupted(executor)
    except click.ClickException as e:
        e.show()
        return e.exit_code
    except NotRootError as e:
        print(f"vfio-isolate: {e}", file=sys.stderr)
        return 1
    except PartitionInvalidError as e:
        what = f"{executor.current} failed: " if executor.current else ""
        _say(executor, f"{what}partition invalid: {e}")
        return 1
    except RolledBackError as e:
        what = f"{executor.current} failed: " if executor.current else ""
        extra = [] if executor.changed else ["nothing was changed"]
        _say(executor, f"{what}{e}", *extra)
        return 1
    except (HostUnsupportedError, JournalError, PreconditionError, SystemctlError) as e:
        what = f"{executor.current} failed: " if executor.current else ""
        _say(executor, f"{what}{e}")
        return 1
    except OSError as e:
        what = f"{executor.current} failed: " if executor.current else ""
        detail = e.strerror or str(e)
        if e.filename:
            detail += f": {e.filename}"
        _say(executor, what + detail)
        return 1
    except Exception as e:
        if output.debug_enabled:
            raise
        what = f"{executor.current} failed: " if executor.current else ""
        _say(executor, f"{what}{type(e).__name__}: {e}", "use -d for a traceback")
        return 1
    finally:
        output.failures.report()


def run_cli():
    sys.exit(main())


if __name__ == '__main__':
    run_cli()
