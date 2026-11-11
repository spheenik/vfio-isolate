## Context

See proposal.md. `CPUSetDelete.execute` moves all tasks to the parent, then
`CPUSet.remove()` does a single `os.rmdir`. The kernel refuses `rmdir` of a cgroup with
`EBUSY` while it has tasks (including ones forked during the move) or live child cgroups.

## Decisions

### Retry only what can succeed
Child cgroups never go away by waiting, so `can_execute` checks for them (subdirectories
of the cgroup) and raises `PreconditionError` before anything runs. For `EBUSY` from
`rmdir`: loop until a deadline of 2 s: move remaining tasks to the parent, `rmdir`,
on `EBUSY` sleep 50 ms. Other errnos are not retried. After the deadline raise an
`OSError`-derived or `PreconditionError` message "cpuset /a is still in use" so `main()`
reports `cpuset-delete failed: ...` with the restore hint.
- Alternative: wait for `cgroup.events` `populated 0` via inotify. Rejected: more code for
  the same outcome; a short poll is enough for a rare race.

### Topology section uses sysfs, not tools
`lscpu -e` and `lstopo` are mentioned as optional, but the section's commands read sysfs
(`topology/thread_siblings_list`, `cache/index3/shared_cpu_list` and `size`,
`/sys/devices/cpu_core/cpus`, `/sys/devices/cpu_atom/cpus`, `node*/cpulist`), because
these exist on every host the tool supports. Shell blocks that are not `vfio-isolate`
invocations are fenced `sh` as well; the README test ignores non-invocation lines.

### AppArmor
One paragraph in the hook recipe: on Ubuntu, `/etc/apparmor.d/usr.sbin.libvirtd` (or a
local override in `/etc/apparmor.d/local/usr.sbin.libvirtd`) needs a rule allowing the
hook to execute `vfio-isolate` (path from `command -v vfio-isolate`, e.g.
`/usr/local/bin/vfio-isolate rmix,` as reported in #4). Marked as reported by users, not
tested here.

## Risks / Trade-offs

- [2 s added to a failing delete] → only on `EBUSY`, which is rare.
- [Topology advice for X3D (V-cache CCD for the VM or not) depends on the workload] → the
  section says how to identify the CCDs and leaves the choice to the user, with the
  common default (VM on the V-cache CCD for games) labeled as a common choice, untested here.
