import sys
import app
import argparse

app.main_parser = argparse.ArgumentParser(prog="vfio-isolate", add_help=False)

# create parsers for them
subparsers = app.main_parser.add_subparsers(dest='command')
for command_class in app.available_command_classes.values():
    command_class.create_parser(subparsers)

# scan command line and generate arguments
commands_to_run = []
argv = sys.argv[1:]
while argv:
    options, argv = app.main_parser.parse_known_args(argv)
    if not options.command:
        break
    command_class = app.available_command_classes[options.command]
    command_instance = command_class()
    for option in options.__dict__:
        if option == "command":
            continue
        setattr(command_instance, option, getattr(options, option))
    commands_to_run.append(command_instance)

# run help if there was no command
if not commands_to_run:
    commands_to_run.append(app.commands.HelpCommand())

# do it
for command in commands_to_run:
    command.execute()
