import sys

debug_enabled = False
verbose_enabled = False


def print_debug(*args, **kwargs):
    if debug_enabled:
        print(*args, **kwargs)


def print_verbose(*args, **kwargs):
    if verbose_enabled:
        print(*args, **kwargs)


def print_error(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
