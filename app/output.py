import sys
from app import verbose_enabled, debug_enabled


def output(*args, **kwargs):
    print(*args, **kwargs)


def output_debug(*args, **kwargs):
    if debug_enabled:
        print(*args, **kwargs)


def output_verbose(*args, **kwargs):
    if verbose_enabled:
        print(*args, **kwargs)


def output_error(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

