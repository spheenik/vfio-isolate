## ADDED Requirements

### Requirement: cpuset-delete removes a busy cpuset reliably
`cpuset-delete` SHALL refuse, before any change, a cpuset that has child cgroups, naming
them. When removing the cpuset fails because it is still in use, it SHALL move the
remaining tasks to the parent again and retry for up to about 2 seconds; if the cpuset is
still in use after that, the command SHALL fail with a message saying the cpuset is still
in use.

#### Scenario: Child cgroups
- **WHEN** `cpuset-delete /a` runs and `/a/b` exists
- **THEN** the command fails naming `/a/b`, before any task is moved

#### Scenario: Task forked during the move
- **WHEN** the first removal of `/a` fails with `EBUSY` because a task appeared in it, and the task is moved on the retry
- **THEN** `/a` is removed and the command succeeds

#### Scenario: Permanently busy
- **WHEN** every removal attempt fails with `EBUSY` for about 2 seconds
- **THEN** the command fails with a message that `/a` is still in use, and the exit status is 1
