## ADDED Requirements

### Requirement: kthread-affinity moves kernel threads
`kthread-affinity mask <cpus>` SHALL remove the CPUs from the affinity of kthreadd and of
every kernel thread that accepts a new affinity, and `kthread-affinity add <cpus>` SHALL
add them. Kernel threads that cannot have their affinity set (PF_NO_SETAFFINITY) SHALL be
skipped. If no CPU would remain for a thread, it SHALL get all online CPUs except the masked
ones; if there are none, the command SHALL be refused. Undo SHALL restore each thread's previous affinity.

#### Scenario: Mask the VM's CPUs
- **WHEN** kthreadd and kswapd0 have affinity 0-31 and `-u j kthread-affinity mask C8-15,24-31` runs
- **THEN** both have affinity 0-7,16-23, and `restore j` sets both back to 0-31

#### Scenario: New kernel threads
- **WHEN** a kernel thread is created after the command ran
- **THEN** it inherits kthreadd's restricted affinity

#### Scenario: Per-CPU kernel threads
- **WHEN** some kernel threads have PF_NO_SETAFFINITY
- **THEN** they are skipped: not touched, not journaled, not reported

#### Scenario: Thread refuses anyway
- **WHEN** a listed kernel thread refuses with EINVAL
- **THEN** it is counted in the summary as expected, and the command succeeds

#### Scenario: Thread gone before undo
- **WHEN** a recorded kernel thread has exited when `restore` runs
- **THEN** its step counts as success

#### Scenario: PID reused before undo
- **WHEN** a recorded PID now belongs to a process that is not a kernel thread, or to a kernel
  thread with a different start time, when `restore` runs
- **THEN** it is not touched and counts as exited

### Requirement: Refused while CPUs are isolated
`kthread-affinity` SHALL fail before any change while CPUs are in isolated cpuset
partitions, naming them and saying the kernel already keeps kernel threads off them.

#### Scenario: Isolated partition active
- **WHEN** CPUs 8-15 are in an isolated partition and `kthread-affinity mask C8-15` runs
- **THEN** it exits 1 naming 8-15, and no affinity changed
