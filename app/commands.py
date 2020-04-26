import argparse

import app
from app.fs import write


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
        print(app.available_command_classes)

        if self.help_command:
            if self.help_command in app.available_command_classes:
                command_class = app.available_command_classes[self.help_command]
                command_class.parser.print_usage()
            else:
                print("The command '{0}' is unknown".format(self.help_command))

        app.main_parser.print_usage()
        print()
        print("The following commands are available:")
        print()
        for command_class in app.available_command_classes.values():
            print(command_class.command_name)
            command_class.parser.print_usage()
            print()


class DropCachesCommand(Command):
    command_name = "drop-caches"

    @classmethod
    def create_parser(cls, subparsers: argparse._SubParsersAction):
        cls.parser = subparsers.add_parser(DropCachesCommand.command_name, help="drop caches", add_help=False)

    def execute(self):
        write("/proc/sys/vm/drop_caches", "3")
        write("/proc/sys/vm/compact_memory", "1")


