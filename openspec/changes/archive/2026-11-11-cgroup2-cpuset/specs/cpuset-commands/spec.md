## MODIFIED Requirements

### Requirement: cpuset-create and cpuset-modify accept only v2-meaningful options
`cpuset-create` and `cpuset-modify` SHALL accept `--cpus` and `--mems` (plus the cpuset
name argument). `cpuset-modify` SHALL additionally accept
`--partition {member,root,isolated}`, and its help text SHALL mark the option as
experimental. They SHALL NOT accept `--cpu-exclusive`, `--mem-exclusive`,
`--mem-migrate`, `--sched-load-balance`, their `--no-` forms, or the short forms
`-ce/-nce`, `-me/-nme`, `-mm/-nmm`, `-lb/-nlb`.

#### Scenario: Removed option is rejected
- **WHEN** a user runs `vfio-isolate cpuset-modify --cpu-exclusive --cpus C0-3 /host`
- **THEN** the tool exits non-zero with a usage error naming the unknown option
- **AND** no command in the chain has made a change

#### Scenario: Supported options still work
- **WHEN** a user runs `vfio-isolate cpuset-modify --cpus C0-3 --mems N0 /host` on a supported host
- **THEN** the cpuset's `cpuset.cpus` and `cpuset.mems` are set to those values

#### Scenario: Invalid partition type
- **WHEN** a user runs `vfio-isolate cpuset-modify --partition exclusive /host`
- **THEN** the tool exits with a usage error listing `member`, `root` and `isolated`
- **AND** no command in the chain has made a change
