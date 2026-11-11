from dataclasses import dataclass
from typing import Generator, List


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
    def can_execute(cls, p, ctx=None):
        return True

    @classmethod
    def describe(cls, p, ctx) -> List[str]:
        """Dry run: what this action would do, as lines of text ("would " is prepended).

        Must not write anything. ctx is the DryRunContext of the chain so far.
        """
        raise NotImplementedError(f"{cls.__name__}.describe")

    batch = False  # dry run: consecutive executions of one command are described together

    @classmethod
    def describe_many(cls, ps, ctx) -> List[str]:
        """Dry run: describe several executions of a batch action (batch = True) at once."""
        return [line for p in ps for line in cls.describe(p, ctx)]

    @classmethod
    def touches(cls, p) -> set:
        """Dry run: resource keys this action changes, e.g. ("cpuset", "/a"), ("irq", 24).

        A later step reading one of them cannot trust values read from disk."""
        raise NotImplementedError(f"{cls.__name__}.touches")

    @classmethod
    def reads(cls, p) -> set:
        """Dry run: resource keys whose current value describe/can_execute use (default: touches)."""
        return cls.touches(p)

    @classmethod
    def overlay(cls, p, ctx) -> None:
        """Dry run: record in ctx what this action would change for later steps."""

    @classmethod
    def execute(cls, p):
        pass

    @classmethod
    def record_undo(cls, p) -> Generator[Execution, None, None]:
        return
        yield

