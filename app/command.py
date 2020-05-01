import argparse

from app import main_parser, available_command_classes
from app.cpuset import CPUSet
from app.numanode import NUMANode
from app.cpumask import CPUMask


class Command:
    command_name = None
    parser = None

    @classmethod
    def create_parser(cls, subparsers: argparse._SubParsersAction):
        raise SystemExit("cannot create parser for base command")

    def execute(self):
        raise SystemExit("cannot execute base command")

    def get_command_name(self):
        return self.__class__.command_name

    def get_parser(self):
        return self.__class__.parser


class HelpCommand(Command):
    command_name = "help"

    def __init__(self):
        self.help_command = None

    @classmethod
    def create_parser(cls, subparsers: argparse._SubParsersAction):
        cls.parser = subparsers.add_parser(HelpCommand.command_name, add_help=False)
        cls.parser.add_argument("help_command", nargs="?", action="store")

    def execute(self):
        if self.help_command:
            if self.help_command in available_command_classes:
                command_class = available_command_classes[self.help_command]
                command_class.parser.print_usage()
                return
            else:
                print("The command '{0}' is unknown".format(self.help_command))

        main_parser.print_usage()
        print()
        print("The following commands are available:")
        print()
        for command_class in available_command_classes.values():
            print(command_class.command_name)
            command_class.parser.print_usage()
            print()


class DropCachesCommand(Command):
    command_name = "drop-caches"

    @classmethod
    def create_parser(cls, subparsers: argparse._SubParsersAction):
        cls.parser = subparsers.add_parser(DropCachesCommand.command_name, help="drop caches", add_help=False)

    def execute(self):
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3")
        with open("/proc/sys/vm/compact_memory", "w") as f:
            f.write("1")


class CreatePartition(Command):
    command_name = "create-partition"

    def __init__(self):
        self.cpus = None
        self.numa_node = None
        self.cpu_exclusive = False
        self.mem_exclusive = False
        self.partition_name = None

    @classmethod
    def create_parser(cls, subparsers: argparse._SubParsersAction):
        cls.parser = subparsers.add_parser(CreatePartition.command_name, help="create a partition", add_help=False)
        cls.parser.add_argument("partition_name", help="name of the new partition")
        group = cls.parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--cpus", "-c", help="CPUs to use")
        group.add_argument("--numa-node", "-n", type=int, help="NUMA node to use")
        cls.parser.add_argument("--cpu-exclusive", "-ce", help="set CPU exclusive", action='store_true')
        cls.parser.add_argument("--mem-exclusive", "-me", help="set MEM exclusive", default=False, action='store_true')

    def execute(self):
        if self.numa_node:
            node = NUMANode(self.numa_node)
            mask = node.get_cpumask()
        else:
            mask = CPUMask(self.cpus)

        cpu_set = CPUSet(self.partition_name)
        cpu_set.create()
        cpu_set.set_cpus(mask)
        if self.cpu_exclusive:
            cpu_set.set_cpu_exclusive(True)
        if self.mem_exclusive:
            cpu_set.set_mem_exclusive(True)


class RemovePartition(Command):
    command_name = "remove-partition"

    def __init__(self):
        self.partition_name = None

    @classmethod
    def create_parser(cls, subparsers: argparse._SubParsersAction):
        cls.parser = subparsers.add_parser(RemovePartition.command_name, help="remove a partition", add_help=False)
        cls.parser.add_argument("partition_name")

    def execute(self):
        CPUSet(self.partition_name).remove()
