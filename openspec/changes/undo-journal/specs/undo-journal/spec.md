## Purpose

Defines how vfio-isolate records what a run changed (`-u <undo-file>`) and how `restore`
puts the system back, including behaviour on failures, repeated runs and old files.

## ADDED Requirements

### Requirement: Undo is recorded before each action
When run with `-u <file>`, the tool SHALL append each action's undo steps to the file,
and make them durable, before that action makes any change. Steps for actions that
never started SHALL NOT be recorded.

#### Scenario: Failure part-way through a chain
- **WHEN** `-u j cpu-governor ... cpuset-modify --cpus C0-3 /a cpuset-modify --cpus C0-3 /missing` fails on the third command
- **THEN** the run exits non-zero and the journal `j` contains the undo of the first two commands
- **AND** `restore j` returns the governor and `/a` to their original values

#### Scenario: cpuset-create fails after its undo was recorded
- **WHEN** `-u j cpuset-create /a` recorded its undo and then failed before `/a` was created
- **THEN** `restore j` succeeds and deletes the journal

#### Scenario: cpuset-delete fails after its undo was recorded
- **WHEN** `-u j cpuset-delete /a` recorded its undo and then failed before `/a` was removed
- **THEN** `restore j` succeeds, `/a` has its original cpus and mems, and the journal is deleted

#### Scenario: Precondition failure records nothing for that action
- **WHEN** `cpuset-create /a` runs with `-u j` and `/a` already exists
- **THEN** the command fails without changing anything
- **AND** `j` contains no step that would delete `/a`

### Requirement: Restore applies undo in the correct order
`restore` SHALL undo actions in reverse order of execution. Within one action, it SHALL
apply that action's undo steps in the order the action recorded them.

#### Scenario: Undo of cpuset-delete
- **WHEN** `-u j cpuset-delete /a` ran on a cpuset with cpus 2-3 and mems 0, then `restore j` runs
- **THEN** `/a` exists again with cpus 2-3 and mems 0

#### Scenario: Undo of a full IRQ mask
- **WHEN** an IRQ had affinity 2, `-u j irq-affinity mask C2-3` ran, then `restore j` runs
- **THEN** the IRQ's affinity is 2

#### Scenario: Chain undone newest-first
- **WHEN** `-u j cpu-governor C0 performance cpu-governor C0 schedutil` ran on a CPU whose governor was `powersave`, then `restore j` runs
- **THEN** CPU 0's governor is `powersave`

### Requirement: An existing undo file is appended to
If the file named by `-u` already exists and is a valid journal, the tool SHALL append
this run's undo records to it. Restoring therefore undoes every recorded run,
newest-first, back to the state before the first one.

#### Scenario: prepare runs twice
- **WHEN** `-u j cpu-governor C0 performance` runs twice on a CPU whose governor was `powersave`, then `restore j` runs
- **THEN** CPU 0's governor is `powersave` and `j` no longer exists

#### Scenario: prepare retried after a partial failure
- **WHEN** a run with `-u j` failed after changing CPU 0's governor, a second run with `-u j` changes the governors of CPUs 0 and 1, then `restore j` runs
- **THEN** both CPUs have their original governors

#### Scenario: Existing file is not a journal
- **WHEN** `-u j` names an existing file that is not a supported journal
- **THEN** the tool exits non-zero before making any change and leaves the file untouched

### Requirement: Restore continues past failures and keeps what failed
`restore` SHALL attempt every step even if some fail, and report each failure on stderr.
If all steps succeed, it SHALL delete the file and exit 0. If any step fails, it SHALL
replace the file with one that contains only the failed steps, in their original order,
and exit non-zero.

#### Scenario: One step fails
- **WHEN** a journal has undo steps for `/a` and `/b`, `/b` no longer exists, and `restore j` runs
- **THEN** `/a` is restored, an error for `/b` is printed, and the exit status is non-zero
- **AND** `j` now contains only the step for `/b`

#### Scenario: Clean restore
- **WHEN** every step of `j` succeeds
- **THEN** `j` is deleted and the exit status is 0

#### Scenario: Missing journal
- **WHEN** `restore j` runs and `j` does not exist
- **THEN** the tool prints an error naming the file and exits non-zero without changing anything

### Requirement: The journal is plain data and handled safely
The journal SHALL be a text format that only describes known actions and their
parameters. Restoring it SHALL NOT execute arbitrary code. The tool SHALL create the
journal with permissions 0600, and SHALL NOT read or write through a symlink at the
given path. It SHALL refuse to append to or restore from a journal that is not owned
by the current user or that is writable by group or others. `restore` SHALL reject a
file that is not a journal in a supported format version. Every rejection SHALL happen
before any command in the chain makes a change.

#### Scenario: Journal permissions
- **WHEN** a run with `-u j` creates `j`
- **THEN** `j` has mode 0600

#### Scenario: Symlink at the journal path
- **WHEN** `-u j` is given and `j` is a symlink (dangling or not)
- **THEN** the tool exits non-zero before making any change, and the link target is untouched

#### Scenario: 0.5.x pickle undo file
- **WHEN** `restore j` runs on an undo file written by vfio-isolate 0.5.x
- **THEN** it exits non-zero without changing anything, with a message that the file is from 0.5.x and must be restored with vfio-isolate 0.5.2

#### Scenario: Journal writable by others
- **WHEN** `restore j` or `-u j` is used and `j` has mode 0666 or is owned by another user
- **THEN** the tool exits non-zero before any command in the chain makes a change

#### Scenario: Invalid journal later in a chain
- **WHEN** `drop-caches restore j` runs and `j` is a 0.5.x pickle file
- **THEN** `drop-caches` is not executed either

#### Scenario: Unknown action in a journal
- **WHEN** a journal names an action this version does not know
- **THEN** `restore` exits non-zero without changing anything
