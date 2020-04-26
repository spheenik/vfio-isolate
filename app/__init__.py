from app.commands import Command
import inspect
import sys

main_parser = None

available_command_classes = {}
for name, cls in inspect.getmembers(sys.modules["app.commands"]):
    if inspect.isclass(cls) and Command in cls.__bases__:
        available_command_classes[cls.command_name] = cls
