# documentation Specification

## Purpose
Defines what the user documentation must cover and how it is kept correct: README and
`--help` describe every command, argument form and exit status, README examples are
checked by the test suite, and breaking changes are recorded in CHANGELOG.md.

## Requirements
### Requirement: README examples are valid invocations
Every `vfio-isolate` invocation in a README shell block, after joining `\` continuations
and substituting variables assigned in the same block, SHALL be accepted by the CLI's
argument parsing and validation on a host matching the example (exit status 0 when
execution is skipped). README shell blocks SHALL contain no line ending in `\` followed by
whitespace, and no prompt prefixes (`#`, `$`) before commands.

#### Scenario: Hook example
- **WHEN** the libvirt hook example's `vfio-isolate` calls are parsed with `HCPUS` and `MCPUS` substituted
- **THEN** every call parses; `cpu-governor` has a CPU argument

#### Scenario: Broken continuation
- **WHEN** a README shell line ends in `\ `
- **THEN** the test suite fails naming the line

### Requirement: README documents every command and argument form
The README SHALL have a section for every CLI command listing all its options and
arguments, SHALL describe the nodeset forms `C` (decimal list), `N` (NUMA nodes) and `M`
(hex mask, kernel `smp_affinity` format), the root requirement, chaining, the undo journal,
per-item failure reporting, and the exit statuses 0, 1, 2 and 130. Suggested undo files
SHALL be under `/run`.

#### Scenario: Command coverage
- **WHEN** the list of CLI commands is compared with the README's command sections
- **THEN** every command has a section (checked by the test suite)

### Requirement: Help text documents argument forms and behavior
`vfio-isolate --help` SHALL describe chaining, the root requirement and the exit statuses.
Every CPU argument's help SHALL name the `C`, `N` and `M` forms; every NUMA argument's
help the `N` form. `-u` help SHALL say that an existing journal is appended to; `restore`
help SHALL say that records are undone newest first, the file is deleted on success and
rewritten with the failed steps otherwise.

#### Scenario: Mask form discoverable
- **WHEN** `vfio-isolate cpuset-modify --help` is run
- **THEN** the `--cpus` help mentions `C`, `N` and `M`

### Requirement: Breaking changes are recorded
`CHANGELOG.md` SHALL list, per released version from 0.6.0 on, the breaking changes and
the new behavior. For 0.6.0 it SHALL name every breaking change recorded in the archived
proposals, at least: cgroup v1 and the v1-only options removed (stay on 0.5.2), hex masks
under `C` replaced by `M`, undo files in a new format with 0.5.x files refused, `-u`
appending to an existing file, root required.

#### Scenario: Upgrading user
- **WHEN** a 0.5.x user reads the 0.6.0 entry
- **THEN** it tells them each breaking change and what to do instead

