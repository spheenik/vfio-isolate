## ADDED Requirements

### Requirement: irq-affinity restricts the default affinity of new IRQs
`irq-affinity mask|add <cpus>` SHALL apply the same operation to
`/proc/irq/default_smp_affinity` before it changes the existing IRQs, and SHALL record a
relative undo: after `mask`, undo adds back exactly the CPUs that were in the default and
were removed; after `add`, undo removes exactly the CPUs that were added. A run that
changes nothing SHALL record nothing for the default. If the file does not exist, the
default SHALL be skipped without a message.

#### Scenario: mask and restore
- **WHEN** the default is 0-31, `-u j irq-affinity mask C8-15` runs and later `restore j`
- **THEN** the default is 0-7,16-31 after the run and 0-31 after the restore

#### Scenario: Overlapping VMs
- **WHEN** the default is 0-31, run A masks C8-15, run B masks C16-23, and A is restored
- **THEN** the default is 0-15,24-31 (A gives back only 8-15; B's CPUs stay excluded)

#### Scenario: add records only new CPUs
- **WHEN** the default is 0-7, `-u j irq-affinity add C4-11` runs and later `restore j`
- **THEN** the default is 0-11 after the run and 0-7 after the restore

#### Scenario: Ordering
- **WHEN** `irq-affinity mask C8-15` runs
- **THEN** the default is written before any existing IRQ's affinity

#### Scenario: File missing
- **WHEN** `/proc/irq/default_smp_affinity` does not exist
- **THEN** the existing IRQs are changed as before and nothing is printed or recorded for the default

### Requirement: A default without an online CPU is refused
`irq-affinity mask <cpus>` SHALL fail its precondition, before any change of that
command, when the resulting default affinity contains no online CPU.

#### Scenario: Masking all online CPUs
- **WHEN** CPUs 0-7 are online and `irq-affinity mask C0-7` runs
- **THEN** the command fails with exit status 1 naming the default IRQ affinity, and neither the default nor any IRQ affinity is changed

### Requirement: Dry run previews the default
In a dry run, `irq-affinity` SHALL print one line for the default affinity with the old
and new CPU list, before the line for the existing IRQs, and nothing when it would not change.

#### Scenario: Preview
- **WHEN** the default is 0-31 and `-n irq-affinity mask C8-15` runs
- **THEN** the output contains `would set default IRQ affinity: 0-31 -> 0-7,16-31` before `would change affinity of ...`
