## Why

Triage of the open GitHub issues left four gaps on `next`: `cpuset-delete` fails
occasionally with `EBUSY` (#9: the cgroup's `rmdir` is tried once, while tasks that fork
during the move can still be in it); the systemd route for `user.slice` (#16) is not
tested on a real kernel; the README's only help for picking CPUs is a pointer to an
unresolved AMD X3D thread (#14); and the libvirt hook fails silently under Ubuntu's
AppArmor profile (#4).

## What Changes

- `cpuset-delete` checks for child cgroups before any change (a cgroup with children
  cannot be removed; this is a precondition error naming them), and when `rmdir` fails
  with `EBUSY` it moves the remaining tasks to the parent again and retries for up to
  about 2 seconds before failing with a message that the cpuset is still in use.
- VM test: `cpuset-modify` on `/user.slice` through the systemd route, with restore.
- README: the X3D note is removed; a hardware-independent section "Choosing CPUs" shows
  how to read the topology from sysfs (SMT siblings, L3/CCD groups incl. X3D V-cache,
  Intel P/E cores, NUMA) and gives the rule of thumb (whole cores, ideally a whole cache
  domain, for the VM; the host keeps CPU 0). Marked as untested on X3D/hybrid hardware.
- README hook section: AppArmor note (Ubuntu's libvirtd profile must allow executing
  `vfio-isolate`).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `cpuset-management`: `cpuset-delete` refuses cpusets with child cgroups and retries a
  busy removal.
- `documentation`: README explains how to choose CPUs from the host topology.

## Impact

- `vfio_isolate/action/cpuset_delete.py`, `vfio_isolate/cpuset.py`; tests in
  `tests/test_cpuset_management.py` and `tests/vm/`; `README.md`, `CHANGELOG.md`.
- Issues #4, #9, #14, #16 become closable at the next release (tracked, not closed now).
