import click
from app.nodeset import CPUNodeSet, NUMANodeSet
from app.cpuset import CPUSet


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
def drop_caches():
    """drop caches"""
    with open("/proc/sys/vm/drop_caches", "w") as f:
        f.write("3")


@cli.command('compact-memory')
def compact_memory():
    """compact memory"""
    with open("/proc/sys/vm/compact_memory", "w") as f:
        f.write("1")


@cli.command('cpuset-create')
@click.argument("cpuset-name", metavar="<cpuset-name>")
@click.option("--cpus", metavar="<cpunodeset|numanodeset>", help="Set the CPU nodes used by the cpuset", callback=cb_cpu_nodeset)
@click.option("--mems", metavar="<numanodeset>", help="Set the NUMA memory nodes used by the cpuset", callback=cb_numa_nodeset)
@click.option("--cpu-exclusive", "-ce", help="Set CPU exclusive", is_flag=True)
@click.option("--mem-exclusive", "-me", help="Set MEM exclusive", is_flag=True)
@click.option("--mem-migrate", "-mm", help="Enable memory migration", is_flag=True)
def cpuset_create(cpuset_name: str, cpus: CPUNodeSet, mems: NUMANodeSet, cpu_exclusive: bool, mem_exclusive: bool, mem_migrate: bool):
    """create a cpuset"""
    cpu_set = CPUSet(cpuset_name)
    cpu_set.create(cpus, mems)
    if cpus:
        cpu_set.set_cpus(cpus)
    if cpu_exclusive:
        cpu_set.set_cpu_exclusive(True)
    if mem_exclusive:
        cpu_set.set_mem_exclusive(True)
    if mem_migrate:
        cpu_set.set_mem_migrate(True)


@cli.command('cpuset-delete')
@click.argument("cpuset-name", metavar="<cpuset-name>")
def cpuset_delete(cpuset_name):
    """delete a cpuset"""
    cpu_set = CPUSet(cpuset_name)
    cpu_set.parent().add_all_from_cpuset(cpu_set)
    cpu_set.remove()


@cli.command('move-tasks')
@click.argument("cpuset-from", metavar="<cpuset-from>")
@click.argument("cpuset-to", metavar="<cpuset-to>")
def move_tasks(cpuset_from, cpuset_to):
    """move tasks between cpusets"""
    set_from = CPUSet(cpuset_from)
    set_to = CPUSet(cpuset_to)
    set_to.add_all_from_cpuset(set_from)


def run_cli():
    cli()


if __name__ == '__main__':
    run_cli()
