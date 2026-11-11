"""Thin wrapper around systemctl for cpuset properties of systemd-owned cgroups.

All subprocess access goes through _run(), so tests can replace it with a fake.
"""
import os
import subprocess
from typing import Dict, Iterable, Optional

from vfio_isolate import fsroot

UNIT_SUFFIXES = (".slice", ".scope", ".service", ".socket", ".mount", ".swap")
LIST_PROPS = ("AllowedCPUs", "AllowedMemoryNodes")
PROBE_UNIT = "system.slice"
TIMEOUT = 30  # seconds per systemctl call

_supports_cache: Dict[str, bool] = {}


class SystemctlError(Exception):
    pass


def _run(args: Iterable[str]) -> str:
    """Run systemctl with args and return its stdout."""
    cmd = ["systemctl", *args]
    try:
        r = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=TIMEOUT,
                           env={**os.environ, "LC_ALL": "C"})
    except FileNotFoundError:
        raise SystemctlError("systemctl not found")
    except subprocess.TimeoutExpired:
        raise SystemctlError(f"{' '.join(cmd)} timed out after {TIMEOUT}s")
    except subprocess.CalledProcessError as e:
        raise SystemctlError(f"{' '.join(cmd)} failed ({e.returncode}): {(e.stderr or '').strip()}")
    return r.stdout


def systemd_running() -> bool:
    return os.path.isdir(fsroot.path("/run/systemd/system"))


def unit_for_cgroup(cpuset_name: str) -> Optional[str]:
    """Return the systemd unit that owns the cgroup, or None if it is not a unit.

    Raises PreconditionError if a unit of that name is loaded but lives elsewhere.
    """
    # imported lazily: the action package imports cpuset, which will import this module
    from vfio_isolate.action.action import PreconditionError

    parts = [p for p in (cpuset_name or "").split("/") if p]
    if not parts or not systemd_running():
        return None
    unit = parts[-1]
    if not unit.endswith(UNIT_SUFFIXES):
        return None
    path = "/" + "/".join(parts)
    cg = _run(["show", "-p", "ControlGroup", "--value", "--", unit]).strip()
    if not cg:
        return None
    if cg != path:
        raise PreconditionError(
            f"{path} looks like systemd unit {unit}, but that unit lives at {cg}")
    return unit


def show(unit: str, props: Iterable[str]) -> Dict[str, str]:
    """Return {prop: raw string}; cpu/node lists are normalised from spaces to commas."""
    props = list(props)
    args = ["show"]
    for p in props:
        args += ["-p", p]
    args += ["--", unit]
    out = _run(args)
    result = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key not in props:
            continue
        if key in LIST_PROPS:
            value = ",".join(value.split())
        result[key] = value
    for p in props:
        result.setdefault(p, "")
    return result


def set_property(unit: str, **props: str) -> None:
    """One `systemctl set-property --runtime` call; an empty value resets the property."""
    if not props:
        return
    _run(["set-property", "--runtime", "--", unit] + [f"{k}={v}" for k, v in props.items()])


def supports(prop: str, unit: str = PROBE_UNIT) -> bool:
    """Whether this systemd knows the property (unknown ones print nothing). Cached."""
    if prop not in _supports_cache:
        out = _run(["show", "-p", prop, "--", unit])
        _supports_cache[prop] = any(l.startswith(prop + "=") for l in out.splitlines())
    return _supports_cache[prop]


def reset_cache() -> None:
    _supports_cache.clear()
