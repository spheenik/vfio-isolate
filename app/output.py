import sys


__verbose = True


def set_verbose(verbose: bool):
    global __verbose
    __verbose = verbose


def output(*args, **kwargs):
    print(*args, **kwargs)


def output_verbose(*args, **kwargs):
    global __verbose
    if __verbose:
        print(*args, **kwargs)


def output_error(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

