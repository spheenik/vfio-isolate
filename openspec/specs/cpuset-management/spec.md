# cpuset-management Specification

## Purpose
Defines how vfio-isolate applies and undoes cpuset settings on cgroup v2: when it
delegates to systemd and when it writes cgroup files itself, which values it records
for undo, how partitions are handled, and how task moves are undone.
## Requirements
### Requirement: systemd-owned cgroups are changed through systemd
When systemd is the init system, and the target cgroup is a systemd unit's cgroup (its
last path component is a unit name and systemd reports that unit's `ControlGroup` as
that path), the tool SHALL apply `--cpus`, `--mems` and `--partition` as runtime unit
properties (`AllowedCPUs=`, `AllowedMemoryNodes=`, `CPUSetPartition=`). It SHALL NOT
write that unit's cgroup files directly.

#### Scenario: Restricting system.slice on a systemd host
- **WHEN** `cpuset-modify --cpus C0-3 /system.slice` runs on a systemd host
- **THEN** `system.slice` has the runtime property `AllowedCPUs=0-3`
- **AND** its `cpuset.cpus.effective` is `0-3`

#### Scenario: Survives a daemon reload
- **WHEN** `system.slice` was restricted by the tool and `systemctl daemon-reload` runs
- **THEN** `system.slice`'s `cpuset.cpus.effective` is still `0-3`

#### Scenario: Undo restores the previous properties
- **WHEN** `-u j cpuset-modify --cpus C0-3 /system.slice` ran on a slice without `AllowedCPUs`, then `restore j` runs
- **THEN** `system.slice` has an empty `AllowedCPUs` again and its effective CPUs equal its parent's

#### Scenario: Unit path mismatch
- **WHEN** the target's last component looks like a unit name but systemd reports a different `ControlGroup` for that unit
- **THEN** the tool exits non-zero before any change, naming the unit and both paths

### Requirement: Other cgroups are changed directly and correctly
For a cgroup that systemd does not own, or on a host without systemd, the tool SHALL
write the cgroup files directly. Before creating or modifying a cgroup, it SHALL ensure
that `cpuset` is enabled in the `cgroup.subtree_control` of every ancestor from the
root down to the target's parent. It SHALL NOT write `subtree_control` of the target
itself.

#### Scenario: Create below a cgroup without the controller
- **WHEN** `cpuset-create --cpus C0-3 /a/b` runs and `/a` exists without `cpuset` in its `subtree_control`
- **THEN** `/a`'s `subtree_control` gains `cpuset`, and `/a/b` exists with `cpuset.cpus` = `0-3`
- **AND** `/a/b`'s own `subtree_control` is unchanged

#### Scenario: Reads never write
- **WHEN** undo is recorded for `cpuset-modify` on a non-systemd cgroup
- **THEN** no cgroup file is written during recording

### Requirement: Undo restores configured values, not effective ones
For directly managed cgroups, undo SHALL record the configured `cpuset.cpus` and
`cpuset.mems` (which may be empty, meaning inherit from the parent) and SHALL restore
exactly those values, including empty.

#### Scenario: Inheriting cgroup
- **WHEN** `/a` has an empty `cpuset.cpus`, `-u j cpuset-modify --cpus C0-3 /a` runs, then `restore j` runs
- **THEN** `/a`'s `cpuset.cpus` is empty again and its effective CPUs equal its parent's

#### Scenario: Create without --cpus inherits
- **WHEN** `cpuset-create /a` runs without `--cpus` or `--mems`
- **THEN** `/a`'s `cpuset.cpus` and `cpuset.mems` are empty (inherit from the parent)

### Requirement: Partitions are opt-in and validated
`cpuset-modify --partition {member,root,isolated}` SHALL set the partition type of the
target. This feature is experimental. After setting it, the tool SHALL read back
`cpuset.cpus.partition`. If the kernel reports the partition as invalid, the command
SHALL fail with the kernel's reason, and the change SHALL remain undoable through the
journal. If systemd owns the target but the installed systemd does not support
`CPUSetPartition=`, the tool SHALL fail before any change.

#### Scenario: Isolated partition for the VM slice
- **WHEN** `cpuset-modify --cpus C4-7 --partition isolated /machine.slice` runs on an 8-CPU host
- **THEN** `/machine.slice`'s `cpuset.cpus.partition` reads `isolated`
- **AND** the effective CPUs of its sibling slices no longer include 4-7

#### Scenario: Invalid partition
- **WHEN** the kernel reports `isolated invalid (<reason>)` after the write
- **THEN** the tool exits non-zero and prints the reason
- **AND** restoring the journal returns the partition type and CPUs to their previous values

#### Scenario: Undo of a partition
- **WHEN** `-u j cpuset-modify --cpus C4-7 --partition isolated /machine.slice` ran, then `restore j` runs
- **THEN** `/machine.slice`'s partition reads `member`, its CPU settings are back to their previous values, and the siblings' effective CPUs include 4-7 again

### Requirement: move-tasks undo moves back only the moved tasks
Undo of `move-tasks <from> <to>` SHALL move back exactly the processes that were in
`<from>` when the command ran and are still alive and in `<to>`. Processes that were
already in `<to>` SHALL stay.

#### Scenario: Pre-existing task stays
- **WHEN** PID 100 is in `/a`, PID 200 is in `/b`, `-u j move-tasks /a /b` runs, then `restore j` runs
- **THEN** PID 100 is in `/a` and PID 200 is in `/b`

### Requirement: Structural commands are rejected on systemd units and the root
`cpuset-create` and `cpuset-delete` SHALL be rejected for a target that is a systemd
unit's cgroup. `cpuset-create` SHALL also be rejected below a systemd unit that does not
delegate its subtree (`Delegate=yes`). `cpuset-modify`, `cpuset-create` and `cpuset-delete` SHALL be rejected
for the root cgroup `/`. All of these rejections SHALL happen before any change.

#### Scenario: Creating below a non-delegated slice
- **WHEN** `cpuset-create /machine.slice/foo` runs on a systemd host and `machine.slice` has `Delegate=no`
- **THEN** the tool exits non-zero before any change, saying the parent is managed by systemd

#### Scenario: Deleting a slice
- **WHEN** `cpuset-delete /system.slice` runs on a systemd host
- **THEN** the tool exits non-zero before any change, saying the cgroup is managed by systemd

### Requirement: cpuset-delete removes a busy cpuset reliably
`cpuset-delete` SHALL refuse, before any change, a cpuset that has child cgroups, naming
them. When removing the cpuset fails because it is still in use, it SHALL move the
remaining tasks to the parent again and retry for up to about 2 seconds; if the cpuset is
still in use after that, the command SHALL fail with a message saying the cpuset is still
in use. A removal that fails because of child cgroups SHALL fail at once, naming them, also
during `restore`. A task that cannot be moved SHALL be counted once per delete, not once per
retry.

#### Scenario: Child cgroups
- **WHEN** `cpuset-delete /a` runs and `/a/b` exists
- **THEN** the command fails naming `/a/b`, before any task is moved

#### Scenario: Child cgroup created before restore
- **WHEN** a journal from `-u j cpuset-create /a` is restored after `/a/b` was created
- **THEN** `restore` fails at once naming `/a/b`, without retrying, and keeps the step in the journal

#### Scenario: Task forked during the move
- **WHEN** the first removal of `/a` fails with `EBUSY` because a task appeared in it, and the task is moved on the retry
- **THEN** `/a` is removed and the command succeeds

#### Scenario: Permanently busy
- **WHEN** every removal attempt fails with `EBUSY` for about 2 seconds
- **THEN** the command fails with a message that `/a` is still in use, and the exit status is 1

