## ADDED Requirements

### Requirement: Nodeset arguments have three explicit forms
A CPU argument SHALL accept `C<list>` (decimal CPU numbers and ranges, e.g. `C0-3,8`),
`N<list>` (NUMA nodes, expanded to their CPUs) and `M<mask>` (a hex CPU mask: groups of
1 to 8 hex digits separated by commas, most significant group first, each group 32 bits,
as in `/proc/irq/*/smp_affinity`, case-insensitive). A NUMA argument SHALL accept only
`N<list>`. `C` SHALL never be read as a mask.

#### Scenario: Decimal list that looks like a mask
- **WHEN** `--cpus C10000000` is given on a host without CPU 10000000
- **THEN** it is a usage error saying the CPU does not exist; it is not read as CPU 28

#### Scenario: Former mask syntax under C
- **WHEN** `--cpus C000000ff` is given
- **THEN** it is a usage error

#### Scenario: Mask
- **WHEN** `Mff,0000000f` is given
- **THEN** the set is CPUs 0-3 and 32-39

#### Scenario: Short mask
- **WHEN** `M3c` is given
- **THEN** the set is CPUs 2-5

### Requirement: Invalid nodesets are usage errors
A syntax error, a reversed range (e.g. `C7-0`), a range ending above 65535, an empty
set (`C`, `N`, `M`, `M0`, or `N` nodes without CPUs given as a CPU argument), or a CPU or
NUMA node that does not exist SHALL be a click usage error (exit status 2) naming the
argument, before anything is changed.

#### Scenario: Reversed range
- **WHEN** `irq-affinity mask C7-0` is given
- **THEN** it is a usage error and nothing is changed

#### Scenario: Empty set
- **WHEN** `cpuset-modify --cpus C /a` is given
- **THEN** it is a usage error

#### Scenario: NUMA node without CPUs
- **WHEN** `--cpus N1` is given and node 1 has memory but no CPUs
- **THEN** it is a usage error

#### Scenario: Syntax error
- **WHEN** `C0-3,,5` is given
- **THEN** it is a usage error naming the value, with no traceback

### Requirement: Complements use the right universe
The complement of a CPU set SHALL be taken within the possible CPUs, and the complement of
a NUMA node set within the possible NUMA nodes.

#### Scenario: NUMA complement
- **WHEN** a host has possible CPUs 0-15 and possible nodes 0-1, and the complement of `N0` is taken
- **THEN** the result is node 1
