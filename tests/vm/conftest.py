"""Guard for the VM suite: these tests change real cgroups and systemd units.

They run only inside the throwaway guest started by scripts/vm-test, which exports
VFIO_ISOLATE_IN_VM=1. A real host (even under sudo, even with systemd as PID 1) skips them.
"""
import os
import subprocess

import pytest


def _pid1():
    try:
        with open("/proc/1/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def _virt():
    try:
        r = subprocess.run(["systemd-detect-virt", "--vm"], capture_output=True, text=True)
    except OSError:
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out and out != "none" else None


def _skip_reason():
    if os.environ.get("VFIO_ISOLATE_IN_VM") != "1":
        return "VFIO_ISOLATE_IN_VM=1 not set (use scripts/vm-test)"
    if os.geteuid() != 0:
        return "not root"
    if _pid1() != "systemd":
        return "PID 1 is not systemd"
    if _virt() is None:
        return "systemd-detect-virt --vm reports no virtual machine"
    return None


def pytest_collection_modifyitems(config, items):
    reason = _skip_reason()
    if reason is None:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    marker = pytest.mark.skip(reason=f"VM tests run only in the scripts/vm-test guest: {reason}")
    for item in items:
        if str(item.path).startswith(here + os.sep):
            item.add_marker(marker)
