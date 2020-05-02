import sys
import app


def print_debug(*args, **kwargs):
    if app.debug_enabled:
        print(*args, **kwargs)


def print_verbose(*args, **kwargs):
    if app.verbose_enabled:
        print(*args, **kwargs)


def print_error(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)




