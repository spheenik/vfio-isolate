## Context

See proposal.md for the motivation. Relevant current state:
- `CPUSet` in `vfio_isolate/cpuset.py` holds the v2 methods.
  - `get_cpus`/`get_mems` read `*.effective`.
  - Every get and set calls `ensure_cpuset_controller_enabled(self)`, which compares
    whole lines of `cgroup.controllers` with "cpuset" (always False) and then writes
    `+cpuset` into the target's own `subtree_control`.
- Actions follow the journal contract from `undo-journal`:
  - `can_execute` raises `PreconditionError`;
  - `record_undo` yields steps in apply order;
  - restore skips `can_execute`.
- The journal codec handles `str`, `int`, `bool`, `None`, nodesets, `IRQ`, `CPU` and
  Enums. It does not handle lists.
- Host facts (systemd 262, kernel 7.2):
  - The root `subtree_control` contains `cpuset`.
  - Top-level slices have empty `AllowedCPUs`.
  - `CPUSetPartition=` is documented in `systemd.resource-control(5)` and requires
    `AllowedCPUs=`.
  - `systemctl show` prints known-but-empty properties as `Name=`.
- Unverified (moderate or low): whether `daemon-reload` touches `cpuset.cpus` of slices
  without `AllowedCPUs`; partition validity when an unrestricted sibling exists; libvirt's
  per-vCPU cpuset writes inside an isolated `machine.slice`. The VM suite answers the
  first two; the third needs a real VM with libvirt and stays a documented risk.

## Goals / Non-Goals

**Goals:**
- One owner per cpuset: systemd for its units, the tool for everything else.
- Correct, write-free reads, and exact undo of configured values.
- Opt-in partitions with kernel validation.
- A VM suite that runs the real kernel and systemd.

**Non-Goals:**
- Reordering chains. The user writes host-restriction before VM partition, as the
  README examples will show (`readme-and-tests`).
- Undoing controller enablement in ancestors' `subtree_control`. It is left enabled:
  harmless, and systemd enables it anyway when any unit has cpuset properties.
- Testing libvirt inside the VM suite.
- Swallowed `add_pid` errors (`error-reporting`).

## Decisions

### 1. `systemd.py`: detection, ownership, properties
- `systemd_running()`: `fsroot.path("/run/systemd/system")` is a directory. This is
  the standard `sd_booted()` check.
- `unit_for_cgroup(cpuset_name) -> str | None`:
  - Only if systemd is running, the path isn't `/`, and the last component has a unit
    suffix (`.slice`, `.scope`, `.service`, `.socket`, `.mount`, `.swap`).
  - Query `systemctl show -p ControlGroup --value <unit>`.
  - Equal to the path → the unit.
  - Empty (no such unit loaded) → `None`, so the cgroup is treated as unowned.
  - Different non-empty path → `PreconditionError`, the spec's mismatch scenario.
- `Systemd.show(unit, props) -> dict` and `Systemd.set_property(unit, **props)` run
  `systemctl` through a single `_run(args)` function. `set_property` uses
  `--runtime`, and an empty value resets.
- `supports(prop)`: the property name appears in `systemctl show <unit>` output, which
  is cached.

Tests replace `_run` through the `fake_host` fixture with a fake. The fake keeps unit
properties and mirrors them into the fake cgroup tree (`AllowedCPUs` →
`cpuset.cpus`/`.effective`, `CPUSetPartition` → `cpuset.cpus.partition`), so
actions are tested end to end.
*Alternative*: the D-Bus API via `busctl`/`dbus-python`. That adds a dependency or
heavier parsing; the `systemctl` CLI is stable and is what users would type.

### 2. One CPUSetModify, two backends, an explicit "reset" value
- `CPUSetModify.Param`: `cpuset_name`, `cpus`, `mems`, `partition`.
  - `None` = don't touch.
  - Empty `CPUNodeSet`/`NUMANodeSet` = reset to inherit/unrestricted.
  - `partition` is a `str` in {member, root, isolated} or `None`.
- `execute` resolves the backend through `unit_for_cgroup`:
  - systemd → one `set_property` call with the non-None fields.
  - direct → file writes.
- **Write order matters for partitions on the direct path** (systemd takes both in one
  call, per probe 3):
  - target partition `member` → write the partition first, then cpus and mems;
  - `root`/`isolated` → cpus and mems first, then the partition.

  This makes forward and undo both valid, since undo of `isolated` is `member` plus
  the old cpus.
- After any partition write, read back `cpuset.cpus.partition`. A value containing
  `invalid` raises `PartitionInvalidError(reason)`, which gives exit 1. The journal
  record was written before execute, so `restore` repairs it.
- `record_undo` reads the *configured* state from the same backend:
  - systemd → `show AllowedCPUs AllowedMemoryNodes CPUSetPartition`;
  - direct → `cpuset.cpus`, `cpuset.mems`, `cpuset.cpus.partition`, normalising
    "isolated invalid (…)" to its base type.

  It emits one CPUSetModify with only the fields the forward action sets, carrying the
  previous values (possibly empty).
- **Empty values on a real kernel:** an inheriting cgroup's `cpuset.cpus` reads as
  `"\n"`. Today that crashes `NodeSet` (the empty check runs before `rstrip`; this
  change pulls in that one-line fix from `error-reporting`). An empty value is written
  as `"\n"`, because `write("")` issues no syscall and cgroupfs ignores truncation.
  The fake tree's inheriting cgroups hold `"\n"`, and the VM suite covers the
  round trip.
- **Previous partition on systemd:** `systemctl show` prints `CPUSetPartition=` (empty)
  when unset. That is recorded as `member`, because restoring an empty value leaves the
  partition invalid (probe 3). Undo is always one `set-property` call carrying the
  partition and the cpus together.
- **Remaining callers of the effective readers:** `CPUSetDelete.record_undo` moves to
  the configured readers and also captures the partition. `CPUSet.create()` without
  `--cpus`/`--mems` leaves the files empty (inherit), instead of copying the parent's
  effective values.
- `get_cpus`/`get_mems` stay as "effective" readers for display use. New
  `get_configured_cpus/mems/partition` serve undo. No getter writes anything.

### 3. Controller enablement only on the direct path, ancestors only
`CPUSet.ensure_controller_path()` walks from the root to the target's **parent**. For
each ancestor whose `cgroup.subtree_control` tokens lack `cpuset`, it writes `+cpuset`.
`create()` and direct-path `set_*` call it; nothing else does. The root's controllers
come from `cgroup_root()`'s validation.

### 4. Preconditions
- `CPUSetCreate`/`CPUSetDelete`: reject the root path `/` and systemd units.
  `CPUSetCreate` also rejects a target whose ancestor is a systemd unit without
  `Delegate=yes`: enabling the controller there would mean writing `subtree_control` of
  a systemd-owned cgroup.
- `CPUSetModify`: reject `/`. If the target is a systemd unit and `partition` is set,
  require `supports("CPUSetPartition")`.

All of this lives in `can_execute`, so it happens before recording, per the journal
contract.

### 5. `move-tasks` with an explicit PID list
- `MoveTasks.Param` gains `pids: Optional[List[int]] = None`.
- `record_undo` captures `list(from.pids())` and yields
  `MoveTasks(from=to, to=from, pids=captured)`.
- With `pids` set, `execute` moves only PIDs that are currently in its `cpuset_from`.
  Others are skipped silently, because they exited or were moved elsewhere.
- The codec learns `Optional[...]` and `List[int]`, and nothing more.
- **Journal compatibility for new fields:** decode treats a missing field that has a
  dataclass default as that default. So adding `partition` and `pids` (and any future
  defaulted field) doesn't make existing journals undecodable. Unknown fields are still
  rejected.

On systemd hosts, `move-tasks` between systemd units still works, but the README
recommends restricting slices instead, because moving PIDs out of units confuses
systemd's accounting.

### 6. VM integration suite
- `tests/vm/` holds pytest tests marked `vm`. They are excluded by default
  (`addopts = -m "not vm"`) and run as root inside the VM against the real `/`.
- Runner: `scripts/vm-test` boots the host kernel with virtme-ng, with systemd as
  PID 1, and runs `pytest -m vm tests/vm` inside. Its exit code is the test result.
- The runner invocation is established (see probe 6); no mkosi fallback is needed.
- Initial VM tests:
  - systemd route sets `AllowedCPUs` and the effective cpus follow;
  - `daemon-reload` keeps it;
  - undo resets it;
  - a direct-path create under a fresh cgroup enables the ancestors' controller;
  - an isolated partition on a test slice is valid once sibling slices are restricted;
  - an isolated partition with unrestricted siblings: valid, and the siblings' effective
    CPUs shrink (probe 4);
  - undo of a partition.

## Risks / Trade-offs

- [Runtime drop-ins persist in `/run` until reboot or restore; a crash leaves the host
  restricted] → That is the same as today's direct writes. The journal still restores
  it. `systemctl revert` is *not* used, because it would also drop the user's own
  runtime settings.
- [systemd versions without `CPUSetPartition=`] → Detected; fails before any change.
- [libvirt writes vCPU cpusets inside `machine.slice`; with an isolated partition, a
  pin outside the partition might fail or invalidate it] → Not testable without
  libvirt. `--partition` is marked experimental, and the README will say "pin vCPUs
  only to partition CPUs".
- [A `systemctl` call per action adds about 10–50 ms] → Only cpuset actions use it, a
  handful per run.
- [Sibling slices that aren't restricted] → Probe 4: the kernel shrinks their effective
  CPUs, and the partition stays valid. No risk.
- [`show` output format may vary across systemd versions] → The parser accepts both
  spaces and commas.

## Probe results (VM: host kernel 7.2.14, systemd 262, 8 vCPUs; logs in the session scratchpad)

1. `set-property --runtime` is synchronous: `cpuset.cpus` and `.effective` are updated
   when it returns (5/5 runs). Read-back right after the call is valid.
2. `systemctl show` prints CPU and node lists **space-separated** (`0-1 4 6-7`); cgroupfs
   uses commas. Space input is accepted by `set-property`. An unset value prints empty
   (`AllowedCPUs=`), and `AllowedCPUs=` resets the file to empty (inherit).
   → Normalise spaces to commas before parsing `show` output.
3. Forward in one call works: `AllowedCPUs=4-7 CPUSetPartition=isolated` gives a valid
   isolated partition. **Reverse with an empty value is broken**: `AllowedCPUs=
   CPUSetPartition=` leaves `isolated invalid (...)`, because the empty partition value
   doesn't make systemd write `member`. No two-call order fixes that either. What works
   is one call with `CPUSetPartition=member AllowedCPUs=`.
   → The partition is never restored as "unset". An empty `CPUSetPartition` recorded from
   `show` is stored as `member`, and the undo is one `set-property` carrying
   `CPUSetPartition=member` plus the previous cpus. The Param's `partition` is
   member/root/isolated/None only; the `""` value from the earlier draft is dropped.
   The unit then keeps `CPUSetPartition=member` as a runtime property, which is
   behaviourally identical to unset.
4. **An unrestricted sibling doesn't block an isolated partition.** The kernel removes
   the exclusive CPUs from the siblings' `cpuset.cpus.effective` (their `cpuset.cpus`
   stays empty). The same holds via systemd and via direct cgroupfs writes. Removing the
   partition gives the CPUs back. → Restricting host slices first is not required. The
   README still shows it, for clarity about where host work runs.
5. `daemon-reload` **resets a directly written `cpuset.cpus`** on a systemd unit without
   `AllowedCPUs`. A value set through `AllowedCPUs` survives `daemon-reload`,
   `daemon-reexec` and property changes on the same or other units. → That confirms the
   systemd route is required; today's README recipe silently loses isolation on any
   reload.
6. The guest doesn't see host `/tmp`. `--rwdir=$S=$S` exposes the scratchpad read-write.
   The dev venv works in the guest when the repo is the cwd. The guest's system python
   lacks pytest. Runner:
   `cd <repo> && vng --run --systemd --user root --cpus 8 --rwdir=$V=$V --exec "<script>"`,
   with the script waiting for `systemctl is-system-running --wait` and then running
   `$V/bin/python -m pytest -m vm tests/vm`. The venv path is a parameter of
   `scripts/vm-test`. Boot takes about 60–90 s.
7. An empty `cpuset.cpus` reads `"\n"`. `printf ''` and truncation are no-ops, while
   `echo > file` (`"\n"`) resets to inherit. That confirms decision 2.
