import json
import os
import sys
from dataclasses import dataclass, is_dataclass

import click

from vfio_isolate.action import *
from vfio_isolate import cpuset, journal
from vfio_isolate.cpu import CPU
from vfio_isolate.cpuset import HostUnsupportedError
from vfio_isolate.irq import IRQS
from vfio_isolate.journal import JournalError
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet
from vfio_isolate.serialize import *


def cb_numa_nodeset(ctx, param, value):
    if not value:
        return None
    if value[0] == 'N':
        s = NUMANodeSet(value[1:])
        if not s.is_valid():
            raise click.BadParameter(f"NUMA nodeset {value} is not valid")
        return s
    else:
        raise click.BadParameter('must start with N')


def cb_cpu_nodeset(ctx, param, value):
    if not value:
        return None
    if value[0] == 'N':
        return cb_numa_nodeset(ctx, param, value).get_cpu_nodeset()
    elif value[0] == 'C':
        if not value:
            return None
        s = CPUNodeSet(value[1:])
        if not s.is_valid():
            raise click.BadParameter(f"CPU nodeset {value} is not valid")
        return s
    else:
        raise click.BadParameter('must start with C or N')


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


@click.group(chain=True)
@click.option('-v', '--verbose', help="enable verbose output", is_flag=True)
@click.option('-d', '--debug', help="enable debug output", is_flag=True)
@click.option('-u', '--undo-file', metavar="<undo-file>",
              help="Create a file that describes the operations needed to undo")
@click.pass_obj
def cli(executor, verbose, debug, undo_file):
    from vfio_isolate import output
    output.verbose_enabled = verbose
    output.debug_enabled = debug
    executor.undo_file = undo_file


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
@click.option("--cpus", metavar="<cpunodeset|numanodeset>", help="Set the CPU nodes used by the cpuset",
              callback=cb_cpu_nodeset)
@click.option("--mems", metavar="<numanodeset>", help="Set the NUMA memory nodes used by the cpuset",
              callback=cb_numa_nodeset)
@click.pass_obj
def cpuset_create(executor, **args):
    """create a cpuset"""
    executor.add(CPUSetCreate, args)
    executor.add(CPUSetModify, args)


@cli.command('cpuset-modify')
@click.argument("cpuset-name", metavar="<cpuset-name>")
@click.option("--cpus", metavar="<cpunodeset|numanodeset>", help="Set the CPU nodes used by the cpuset",
              callback=cb_cpu_nodeset)
@click.option("--mems", metavar="<numanodeset>", help="Set the NUMA memory nodes used by the cpuset",
              callback=cb_numa_nodeset)
@click.pass_obj
def cpuset_modfify(executor, **args):
    """modify a cpuset"""
    executor.add(CPUSetModify, args)


@cli.command('cpuset-delete')
@click.argument("cpuset-name", metavar="<cpuset-name>")
@click.pass_obj
def cpuset_delete(executor, **args):
    """delete a cpuset"""
    executor.add(CPUSetDelete, args)


@cli.command('move-tasks')
@click.argument("cpuset-from", metavar="<cpuset-from>")
@click.argument("cpuset-to", metavar="<cpuset-to>")
@click.pass_obj
def move_tasks(executor, **args):
    """move tasks between cpusets"""
    executor.add(MoveTasks, args)


@cli.command('irq-affinity')
@click.argument("operation", type=EnumChoice(IRQAffinityOperation))
@click.argument("cpus", metavar="<cpunodeset|numanodeset>", callback=cb_cpu_nodeset)
@click.pass_obj
def irq_affinity(executor, **args):
    """manipulate the IRQ affinity"""
    for irq in IRQS.active():
        executor.add(IRQAffinity, IRQAffinity.Param(
            irq=irq,
            operation=args["operation"],
            cpus=args["cpus"]
        ))


@cli.command('cpu-governor')
@click.argument("governor")
@click.argument("cpus", metavar="<cpunodeset|numanodeset>", callback=cb_cpu_nodeset)
@click.pass_obj
def cpu_governor(executor, **args):
    """set the CPU governor for the given CPUs"""
    for n in args["cpus"]:
        cpu = CPU(n)
        executor.add(CPUGovernor, CPUGovernor.Param(
            cpu=cpu,
            governor=args["governor"]
        ))


@cli.command('restore')
@click.argument("undo-file", metavar="<undo-file>")
@click.pass_obj
def restore(executor, undo_file):
    """restore a previous state using an undo file"""
    if executor.undo_file:
        raise click.UsageError("-u/--undo-file cannot be combined with restore")
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
        self.restore_ids = set()  # (st_dev, st_ino) of journals already queued for restore

    def add(self, action_class, params):
        if not is_dataclass(params):
            params = unserialize(action_class.Param, params)
        self.executions.append(Execution(action=action_class, params=params))

    def add_restore(self, batch):
        self.executions.append(batch)

    def _needs_cgroup(self):
        for e in self.executions:
            steps = [s for r in e.records for s in r] if isinstance(e, RestoreBatch) else [e]
            if any(s.action.needs_cgroup for s in steps):
                return True
        return False

    def run(self) -> int:
        # fail before touching anything (record_undo reads cgroup files too)
        if self._needs_cgroup():
            cpuset.cgroup_root()
        appender = journal.open_for_append(self.undo_file) if self.undo_file else None
        rc = 0
        try:
            for e in self.executions:
                if isinstance(e, RestoreBatch):
                    rc = max(rc, self._restore(e))
                    continue
                if e.action.can_execute(e.params) is False:
                    raise PreconditionError(f"{e.action.name}: precondition failed")
                steps = list(e.action.record_undo(e.params))
                if appender:
                    appender.append(steps)
                e.action.execute(e.params)
        finally:
            if appender:
                appender.close()
        return rc

    @staticmethod
    def _restore(batch) -> int:
        failed_records = []
        # newest record first, steps within a record in recorded order
        for record in reversed(batch.records):
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


def main(argv=None) -> int:
    executor = Executor()
    try:
        rv = cli.main(args=argv, prog_name="vfio-isolate", standalone_mode=False, obj=executor)
        if isinstance(rv, int):
            return rv
        return executor.run()
    except click.exceptions.Exit as e:
        return e.exit_code
    except click.exceptions.Abort:
        return 1
    except click.ClickException as e:
        e.show()
        return e.exit_code
    except (HostUnsupportedError, JournalError, PreconditionError) as e:
        print(f"vfio-isolate: {e}", file=sys.stderr)
        return 1


def run_cli():
    sys.exit(main())


if __name__ == '__main__':
    run_cli()
