## ADDED Requirements

### Requirement: README explains how to choose CPUs
The README SHALL explain, independent of CPU model, how to find SMT siblings, cache
(L3) domains, hybrid core types and NUMA nodes from sysfs, and how to split CPUs between
host and VM based on them. Advice for hardware the project has not tested SHALL be marked
as untested. The README SHALL NOT refer users to issue threads for setup instructions.

#### Scenario: X3D user
- **WHEN** a user with a CPU whose CCDs have different L3 sizes reads the section
- **THEN** it tells them how to see which CPUs share which L3 and its size, without naming a CPU model as tested
