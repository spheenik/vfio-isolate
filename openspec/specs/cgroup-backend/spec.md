# cgroup-backend Specification

## Purpose
Defines what vfio-isolate requires of the host's cgroup setup, how it locates the
cgroup v2 hierarchy it operates on, and how it fails when the host does not qualify.
## Requirements
### Requirement: cgroup v2 is required for cpuset operations
The tool SHALL perform cpuset operations only on a cgroup v2 (unified) hierarchy that
has the cpuset controller available at its root. It SHALL NOT read or write any
cgroup v1 cpuset hierarchy.

#### Scenario: Pure cgroup v2 host
- **WHEN** a cgroup2 filesystem is mounted and its root `cgroup.controllers` lists `cpuset`
- **THEN** cpuset commands operate on that cgroup2 mount

#### Scenario: cgroup2 mounted somewhere other than /sys/fs/cgroup
- **WHEN** the only cgroup2 mount is at a non-standard path
- **THEN** the tool uses that mount point

### Requirement: Unsupported hierarchies are rejected before any change
When a command chain includes at least one command that touches cpusets and the host
does not meet the cgroup v2 requirement, the tool SHALL exit with a non-zero status
and a one-line error naming the problem, before any command in the chain makes a
change. The error SHALL mention that cgroup v1 users need vfio-isolate 0.5.x.

#### Scenario: Hybrid layout with cpuset on v1
- **WHEN** a cgroup v1 hierarchy with the cpuset controller is mounted (with or without a cgroup2 mount)
- **THEN** the tool exits non-zero with an error stating the cpuset controller is bound to cgroup v1
- **AND** no command in the chain has made a change

#### Scenario: No cgroup2 mount
- **WHEN** no cgroup2 filesystem is mounted
- **THEN** the tool exits non-zero with an error stating cgroup v2 was not found

#### Scenario: cpuset controller unavailable
- **WHEN** cgroup2 is mounted but its root `cgroup.controllers` does not list `cpuset`
- **THEN** the tool exits non-zero with an error stating the cpuset controller is not available

#### Scenario: Chain mixing cpuset and non-cpuset commands
- **WHEN** a chain such as `drop-caches cpuset-modify ...` runs on an unsupported host
- **THEN** `drop-caches` is not executed either

### Requirement: Commands not touching cpusets work without cgroup v2
`--help`, per-command help, and command chains made up only of commands that do not
touch cpusets (`drop-caches`, `compact-memory`, `irq-affinity`, `cpu-governor`) SHALL
work regardless of the host's cgroup setup.

#### Scenario: Help on a host without cgroup2
- **WHEN** `vfio-isolate --help` runs on a host with no cgroup2 mount
- **THEN** usage is printed and the exit status is 0

#### Scenario: Non-cpuset chain on a cgroup v1 host
- **WHEN** `vfio-isolate drop-caches` runs on a cgroup v1 host
- **THEN** the command runs without a cgroup error

