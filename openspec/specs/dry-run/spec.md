# dry-run Specification

## Purpose
Defines `-n/--dry-run` and `restore -n`: previewing what a command line or a restore
would do, with the guarantee that a preview changes nothing on the host.
## Requirements
### Requirement: Dry run changes nothing
With `-n`/`--dry-run`, the tool SHALL parse and validate the command line, check each
action's preconditions in order, and print what each action would do, and SHALL NOT
change any file under `/sys`, `/proc` or the cgroup tree, call state-changing
`systemctl` verbs, create or modify a journal, or take the run lock.

#### Scenario: Preview a hook line
- **WHEN** `vfio-isolate -n -u j cpuset-modify --cpus C0-7 /system.slice irq-affinity mask C8-15` runs
- **THEN** it prints the planned changes with current and new values, says it would record undo in `j`, exits 0, and `j` does not exist afterwards

#### Scenario: Precondition fails
- **WHEN** a dry run reaches `cpuset-delete /missing`
- **THEN** it prints the precondition error prefixed `dry run:`, stops there and exits 1

### Requirement: Dry run follows the chain
A dry run SHALL treat cpusets that earlier steps would create or delete as existing or
gone for later steps. A value an earlier step would change SHALL be marked `(after earlier
steps)` instead of being read from the host, and a precondition that depends on such a value
SHALL be reported as checked only in a real run, not evaluated against stale state.

#### Scenario: Create then move
- **WHEN** `-n cpuset-create --cpus C0-7 /a move-tasks / /a` runs and `/a` does not exist
- **THEN** both steps are described, no precondition fails, and `/a` still does not exist

#### Scenario: Same unit modified twice
- **WHEN** `-n cpuset-modify --cpus C0-3 /a cpuset-modify --cpus C0-1 /a` runs
- **THEN** the second step shows `cpus (after earlier steps) -> 0-1`

#### Scenario: Partition then workqueue-affinity
- **WHEN** `-n cpuset-modify --cpus C4-7 --partition isolated /a workqueue-affinity mask C4-7` runs and the isolated CPUs of the chain so far are exactly known (`/a` is not a partition yet, or was created by an earlier step)
- **THEN** the workqueue step refuses like a real run (`CPUs 4-7 are in isolated cpuset partitions ...`, prefixed `dry run:`) and the exit status is 1; the same holds when `/a` was created earlier in the chain

#### Scenario: Isolation not exactly known
- **WHEN** an earlier step changes the isolated CPUs in a way the preview cannot know exactly (a partition without `--cpus`, new CPUs for a partition or for a parent of one, deleting or changing a partition) and `workqueue-affinity mask C0` follows
- **THEN** the workqueue step shows `(after earlier steps)` as its current mask and is followed by `(precondition checked only in a real run: depends on earlier steps)`, and the exit status is 0

#### Scenario: IRQ mask then add
- **WHEN** `-n irq-affinity mask C0-3 irq-affinity add C0` runs
- **THEN** the second summary ends with `N depend on earlier steps`

### Requirement: Dry run without root
A dry run SHALL NOT require root. Values it cannot read SHALL be shown as unknown
instead of failing.

#### Scenario: Non-root preview
- **WHEN** a non-root user runs `vfio-isolate -n irq-affinity mask C8-15`
- **THEN** it exits 0 and prints the planned change

### Requirement: Undo file check
With `-n -u <file>` the preview SHALL apply the checks a real run applies to the journal, with a real run's owner (root): the file's type, owner and mode, the header (including 0.5.x detection), every record, and a missing parent directory. A truncated last line is reported, not trimmed. A journal the previewing user cannot read SHALL NOT fail the preview but be reported as checked only in a real run.

#### Scenario: Unreadable journal
- **WHEN** a non-root user previews with `-u` on a root-owned 0600 journal
- **THEN** it prints `would record undo in <file> (existing journal not readable as this user; checked only in a real run)` and exits 0

#### Scenario: Journal owned by the user
- **WHEN** the journal exists and is owned by a non-root user
- **THEN** the preview fails like a real run (`not owned by the current user`)

### Requirement: Restore preview
`restore -n <journal>` (and `-n restore <journal>`) SHALL validate the journal like `restore` and print the undo steps
in the order they would be applied (without `can_execute`, as a real restore), without changing the host or the journal. Steps follow the same chain rules, newest record first.

#### Scenario: Preview an undo file
- **WHEN** `restore -n j` runs on a journal with two records
- **THEN** it prints the steps of the newer record first, exits 0, and `j` is unchanged

#### Scenario: Dry-run option after the file
- **WHEN** `restore j -n` runs
- **THEN** it is a usage error (exit status 2), `j` is unchanged and nothing is restored

