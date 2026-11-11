from dataclasses import dataclass
from typing import Generator


class PreconditionError(Exception):
    pass


class RolledBackError(PreconditionError):
    """Raised by an action that undid its own changes before failing."""


@dataclass
class Execution:
    action: type
    params: object


class Action:
    name = None
    needs_cgroup = False

    @classmethod
    def can_execute(cls, p):
        return True

    @classmethod
    def execute(cls, p):
        pass

    @classmethod
    def record_undo(cls, p) -> Generator[Execution, None, None]:
        return
        yield

