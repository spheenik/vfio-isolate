import os


class NotRootError(Exception):
    pass


def require_root():
    """Refuse to continue unless running as root (runs that change the host need it)."""
    if os.geteuid() != 0:
        raise NotRootError("must be run as root")
