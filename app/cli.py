import click

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
def cli(verbose, debug):
    from app import output
    output.verbose_enabled = verbose
    output.debug_enabled = debug


@cli.command('drop-caches')
def drop_caches(**args):
    """drop caches"""
    action_drop_caches(unserialize(ParamDropCaches, args))


@cli.command('compact-memory')
def compact_memory(**args):
    """compact memory"""
    action_compact_memory(unserialize(ParamCompactMemory, args))


@cli.command('cpuset-create')
@click.argument("cpuset-name", metavar="<cpuset-name>")
@click.option("--cpus", metavar="<cpunodeset|numanodeset>", help="Set the CPU nodes used by the cpuset", callback=cb_cpu_nodeset)
@click.option("--mems", metavar="<numanodeset>", help="Set the NUMA memory nodes used by the cpuset", callback=cb_numa_nodeset)
@click.option("--cpu-exclusive", "-ce", help="Set CPU exclusive", is_flag=True)
@click.option("--mem-exclusive", "-me", help="Set MEM exclusive", is_flag=True)
@click.option("--mem-migrate", "-mm", help="Enable memory migration", is_flag=True)
def cpuset_create(**args):
    """create a cpuset"""
    action_cpuset_create(unserialize(ParamCPUSetCreate, args))


@cli.command('cpuset-delete')
@click.argument("cpuset-name", metavar="<cpuset-name>")
def cpuset_delete(**args):
    """delete a cpuset"""
    action_cpuset_delete(unserialize(ParamCPUSetDelete, args))


@cli.command('move-tasks')
@click.argument("cpuset-from", metavar="<cpuset-from>")
@click.argument("cpuset-to", metavar="<cpuset-to>")
def move_tasks(**args):
    """move tasks between cpusets"""
    action_move_tasks(unserialize(ParamMoveTasks, args))


def run_cli():
    cli()


if __name__ == '__main__':
    run_cli()
