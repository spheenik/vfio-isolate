## ADDED Requirements

### Requirement: workqueue-affinity restricts unbound workqueues
`workqueue-affinity mask <cpus>` SHALL remove the CPUs from the global unbound workqueue
cpumask, and `workqueue-affinity add <cpus>` SHALL add them, starting from the requested
mask. While CPUs are in isolated cpuset partitions the command SHALL be refused before any
change. A result with no online CPU SHALL be refused before any change. Undo SHALL restore
the previous requested mask without the CPUs isolated at undo time.

#### Scenario: Mask the VM's CPUs
- **WHEN** the requested mask is CPUs 0-31 and `-u j workqueue-affinity mask C8-15,24-31` runs
- **THEN** the mask is CPUs 0-7,16-23, and `restore j` sets it back to 0-31

#### Scenario: Nothing would remain
- **WHEN** `workqueue-affinity mask C0-31` runs on a 32-CPU host
- **THEN** it fails before writing, saying no CPU would remain

#### Scenario: Isolated partition active
- **WHEN** CPUs 8-15 are in an isolated partition and `workqueue-affinity add C8-15` runs
- **THEN** it fails before writing, naming CPUs 8-15

#### Scenario: Only offline CPUs would remain
- **WHEN** CPUs 0-7 are possible, 0-3 are online and `workqueue-affinity mask C0-3` runs
- **THEN** it fails before writing, saying no CPU would remain

#### Scenario: Undo while a partition is active
- **WHEN** a partition on CPUs 4-7 was created after the workqueue step in the same chain
  (`-u j workqueue-affinity mask C2 cpuset-modify --partition isolated --cpus C4-7 /x`)
  and `restore j` runs
- **THEN** the partition is removed first (newest record first), and the mask written is the
  full previous mask
