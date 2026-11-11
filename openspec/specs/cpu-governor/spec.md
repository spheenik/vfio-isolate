# cpu-governor Specification

## Purpose
Defines how `cpu-governor` validates the requested governor against every selected CPU
before any action of the run executes.

## Requirements
### Requirement: The governor is validated before any change
`cpu-governor <governor> <cpus>` SHALL check every selected CPU while arguments are parsed.
A CPU without a `cpufreq` directory, or whose `scaling_available_governors` does not list
the governor, SHALL make the run a usage error (exit status 2) that names those CPUs and
the governors available on them. No action of the run SHALL execute.

#### Scenario: Unknown governor
- **WHEN** `drop-caches cpu-governor schedutil C0-3` runs and the CPUs offer only `performance powersave`
- **THEN** it is a usage error listing `performance powersave`, and caches were not dropped

#### Scenario: No cpufreq
- **WHEN** CPU 5 has no `cpufreq` directory and `cpu-governor performance C4-5` runs
- **THEN** it is a usage error naming CPU 5

