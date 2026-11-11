## ADDED Requirements

### Requirement: Runs that change the host require root
A run that queues any action or `restore` SHALL be refused with
`vfio-isolate: must be run as root` and exit status 1 when the effective UID is not 0,
before any action, journal read or write, or `systemctl` call. `--help` and usage
errors SHALL NOT require root.

#### Scenario: Unprivileged run
- **WHEN** a non-root user runs `vfio-isolate drop-caches`
- **THEN** stderr shows `vfio-isolate: must be run as root`, the exit status is 1 and nothing was written

#### Scenario: Unprivileged restore
- **WHEN** a non-root user runs `vfio-isolate restore j`
- **THEN** stderr shows `vfio-isolate: must be run as root` and the exit status is 1

#### Scenario: Unprivileged help
- **WHEN** a non-root user runs `vfio-isolate --help`
- **THEN** the help is printed and the exit status is 0

### Requirement: Per-item failures are reported without stopping the run
When `irq-affinity` or `move-tasks` (including their undo steps during `restore`) cannot
change one IRQ or task, the run SHALL continue and the exit status SHALL NOT change
because of it, with one exception: when one `irq-affinity` or `move-tasks` action (not a
`restore` step) attempted at least one item, changed none, and at least one of its
failures was not an expected one, the run SHALL continue but end with exit status 1 and
the line `vfio-isolate: <command>: no IRQ could be changed` (or `no task could be moved`). Expected failures SHALL be counted per kind and reported once at the end of
the run on stderr, one line per kind; with `-v` each item SHALL be listed. Expected
failures are: IRQ `EIO` (kernel-managed IRQ), IRQ `ENOENT` (IRQ gone), task `EINVAL`
(kernel thread), task `ESRCH` (task exited). Any other errno SHALL be reported as a
warning naming the item and the error the first time it occurs for that kind of item;
further items failing with the same errno SHALL only be counted and summarized at the end.

#### Scenario: Managed IRQs
- **WHEN** `irq-affinity mask C2-5` runs and 3 IRQs reject the write with `EIO`
- **THEN** stderr has one line saying 3 IRQs are kernel-managed and kept their affinity, the other IRQs are changed and the exit status is 0

#### Scenario: Listing items
- **WHEN** the same run uses `-v`
- **THEN** the 3 IRQ numbers are listed

#### Scenario: Unexpected per-item error
- **WHEN** writing one IRQ's affinity fails with `EINVAL`
- **THEN** stderr has a warning naming that IRQ and the error, the run continues and the exit status is 0

#### Scenario: Same unexpected error for every task
- **WHEN** `move-tasks /a /b` runs and every move fails with `EBUSY`
- **THEN** stderr has one warning for the first task, one summary line with the count of the rest and `vfio-isolate: move-tasks: no task could be moved`, and the exit status is 1

#### Scenario: Only expected failures
- **WHEN** `move-tasks / /b` runs and every remaining task is a kernel thread
- **THEN** stderr has the kernel-thread summary and the exit status is 0

#### Scenario: Kernel threads
- **WHEN** `move-tasks / /host.slice` runs and kernel threads reject the move with `EINVAL`
- **THEN** stderr has one line with their count and the exit status is 0

### Requirement: Failures that stop a run name the command and the way back
When an action fails while it is checked, recorded or executed, the run SHALL stop and
print `vfio-isolate: <command> failed: <reason>` on stderr and exit with status 1. The
message SHALL add a hint: with `-u` and at least one undo record written in this run, that
`vfio-isolate restore <file>` undoes the changes made so far; without `-u` and once any
action has started executing, that changes made before the failure remain; otherwise no
hint. An exception that is not an `OSError` or a known vfio-isolate error SHALL print one
line with `use -d for a traceback`; with `-d` the traceback SHALL be shown.

#### Scenario: Write fails with journal
- **WHEN** `-u j cpuset-modify --cpus C0-3 /a drop-caches` runs and writing `/proc/sys/vm/drop_caches` fails with `EACCES`
- **THEN** stderr shows `vfio-isolate: drop-caches failed:` with the reason and a hint to run `vfio-isolate restore j`, and the exit status is 1

#### Scenario: Write fails without journal
- **WHEN** the same run has no `-u`
- **THEN** the message says the changes made before the failure remain

#### Scenario: Known error after an earlier change
- **WHEN** `-u j cpuset-modify --cpus C0-3 /a move-tasks /a /missing` runs and `/missing` does not exist
- **THEN** stderr shows `vfio-isolate: move-tasks failed:` with the precondition message and a hint to run `vfio-isolate restore j`, and the exit status is 1

#### Scenario: Failure before any change
- **WHEN** the first action of a run fails its precondition
- **THEN** the message has no hint

#### Scenario: Unexpected exception
- **WHEN** an action raises an unexpected exception without `-d`
- **THEN** stderr shows one line naming the command and the error, plus `use -d for a traceback`; no traceback is printed

### Requirement: Interrupts are reported
On `SIGINT`, vfio-isolate SHALL exit with status 130. During execution it SHALL print
which command was interrupted (and with `-u` the restore hint) and close the journal; before
the first action it SHALL say that nothing was changed.

#### Scenario: Ctrl-C with journal
- **WHEN** a run with `-u j` is interrupted during `move-tasks`
- **THEN** stderr names `move-tasks` and suggests `vfio-isolate restore j`, `j` holds every record written so far, and the exit status is 130
