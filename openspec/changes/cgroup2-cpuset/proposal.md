## Why

On a systemd host, vfio-isolate writes `cpuset.cpus` of systemd's slices behind
systemd's back. systemd can rewrite those files, and undo can then restore the wrong
thing. Several cpuset behaviours are also simply wrong:
- The controller check is always false, and writes `+cpuset` into the target's own
  `subtree_control` on every read.
- Undo captures `cpuset.cpus.effective`, so restore turns "inherit from parent" into a
  fixed CPU list.
- `move-tasks` undo moves back every task in the target, including ones that were
  there before.
- `cpuset-create` only works because a read happens to enable the controller in the
  parent.

systemd exposes both `AllowedCPUs=` and `CPUSetPartition=`, so it can own all of this.
`CPUSetPartition=` is confirmed in systemd 262; the version that introduced it is
unknown, so the tool checks for support at runtime. The kernel's isolated partitions, which the kernel docs recommend over
`isolcpus`, become reachable as a by-product.

## What Changes

- On a host where systemd is PID 1, `cpuset-modify` on a cgroup that is a systemd unit
  (`*.slice`, `*.scope`, `*.service`, …) goes through
  `systemctl set-property --runtime <unit> AllowedCPUs=… AllowedMemoryNodes=…`. Undo
  records and restores the unit's previous property values, where empty means
  unrestricted.
- Everywhere else (no systemd, or a cgroup systemd doesn't own), the tool writes the
  cgroup files directly as before, but correctly:
  - it enables the cpuset controller in each ancestor's `subtree_control` before
    creating or modifying a child;
  - it reads and restores the *configured* `cpuset.cpus`/`cpuset.mems`, including empty.
- New experimental option `cpuset-modify --partition {member,root,isolated}`. With
  systemd it maps to `CPUSetPartition=`, otherwise to `cpuset.cpus.partition`. If the
  kernel reports the resulting partition as invalid, the command fails.
- `move-tasks` undo moves back exactly the tasks it moved.
- `cpuset-create`, `cpuset-delete` and modifying the root cgroup `/` are rejected for
  systemd-owned units or the root, where they make no sense.
- A VM-based integration suite (virtme-ng booting the host kernel with systemd) for
  behaviour the fake tree can't show: systemd routing, reload robustness, partitions.

## Capabilities

### New Capabilities
- `cpuset-management`: who owns a cpuset (systemd or direct), how values are applied
  and undone, controller enablement, partitions, and task moves.

### Modified Capabilities
- `cpuset-commands`: `cpuset-modify` gains `--partition`, and the option-surface
  requirement changes accordingly.

## Impact

- Code: `vfio_isolate/cpuset.py` (controller logic, configured reads, partition), new
  `vfio_isolate/systemd.py` (detection, `show`, `set_property` via `systemctl`),
  `action/cpuset_*.py`, `action/move_tasks.py`, `cli.py`, `journal.py` (codec: list of
  ints, new Param fields).
- New runtime dependency on the `systemctl` binary when systemd is detected.
- Test infrastructure: `tests/vm/` plus a runner script. It needs `virtme-ng` and
  `/dev/kvm` locally and is not part of the default `pytest` run.
- Behaviour change for systemd users: values now persist across `daemon-reload` but
  live in runtime drop-ins (`/run/systemd/system.control/`) until restored or reboot.
