import click
import pickle

from dataclasses import is_dataclass
from app.action import *
from app.nodeset import CPUNodeSet, NUMANodeSet
from app.serialize import *

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


@click.group(chain=True)
@click.option('-v', '--verbose', help="enable verbose output", is_flag=True)
@click.option('-d', '--debug', help="enable debug output", is_flag=True)
@click.option('-u', '--undo-file', metavar="<undo-file>", help="Create a file that describes the operations needed to undo")
@click.pass_obj
def cli(executor, verbose, debug, undo_file):
    from app import output
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
@click.option("--cpus", metavar="<cpunodeset|numanodeset>", help="Set the CPU nodes used by the cpuset", callback=cb_cpu_nodeset)
@click.option("--mems", metavar="<numanodeset>", help="Set the NUMA memory nodes used by the cpuset", callback=cb_numa_nodeset)
@click.option("--cpu-exclusive", "-ce", help="Set CPU exclusive", is_flag=True)
@click.option("--mem-exclusive", "-me", help="Set MEM exclusive", is_flag=True)
@click.option("--mem-migrate", "-mm", help="Enable memory migration", is_flag=True)
@click.pass_obj
def cpuset_create(executor, **args):
    """create a cpuset"""
    executor.add(CPUSetCreate, args)


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


@cli.command('restore')
@click.argument("undo-file", metavar="<undo-file>")
@click.pass_obj
def restore(executor, undo_file):
    """restore a previous state using an undo file"""
    with open(undo_file, "rb") as f:
        executions = pickle.load(f)
    for e in executions:
        executor.add(e.action, e.params)


def run_cli():

    class Executor:
        def __init__(self):
            self.executions = []
            self.undo = []
            self.undo_file = None

        def add(self, action_class, params):
            if not is_dataclass(params):
                params = unserialize(action_class.Param, params)
            self.executions.append(Execution(action=action_class, params=params))

        def run(self):
            for e in self.executions:
                undo = e.action.record_undo(e.params)
                if undo:
                    self.undo.append(undo)
                e.action.execute(e.params)
            if self.undo_file:
                with open(self.undo_file, "wb") as f:
                    pickle.dump(self.undo[::-1], f)

    executor = Executor()
    cli(standalone_mode=False, obj=executor)
    executor.run()


if __name__ == '__main__':
    run_cli()
