# hugepages Specification

## Purpose
Defines `hugepages`: adding pages to the kernel's hugepage pool for a VM with relative undo,
rolling back a shortfall so no partial pool is left behind.
## Requirements
### Requirement: hugepages adds pages to the pool
`hugepages [--node N<n>] <pagesize> <amount>` SHALL add `<amount>` of memory in pages of
`<pagesize>` to the hugepage pool, system-wide or on NUMA node `<n>`, by raising
`nr_hugepages` by `<amount>` divided by the page size from its current value. Its undo
SHALL release the same number of pages of the same pool, never below zero.

#### Scenario: Add pages
- **WHEN** the 2M pool holds 4 pages and `-u j hugepages 2M 16M` runs
- **THEN** the pool holds 12 pages and the command succeeds

#### Scenario: Undo releases what was added
- **WHEN** after that, another run has added 4 more pages (16), and `restore j` runs
- **THEN** the pool holds 8 pages

#### Scenario: Overlapping VMs stop in either order
- **WHEN** run A adds 8 pages to an empty pool, run B adds 8, then A is restored, then B
- **THEN** the pool is empty at the end

#### Scenario: Release while pages are in use
- **WHEN** a release lowers `nr_hugepages` and the kernel keeps pages that are still in use
- **THEN** the release succeeds

### Requirement: A shortfall fails and is rolled back
If the read-back count after adding is lower than asked, the command SHALL write the
previous count back, fail with exit status 1 and a message naming how much memory it got
of how much, the page size and the node if given, and SHALL leave no undo record for itself
in the journal.

#### Scenario: Kernel allocates fewer pages
- **WHEN** `-u j hugepages 1G 6G` runs and the kernel allocates only 2 pages
- **THEN** the pool is back at its previous count, the message says it got 2G of 6G in 1G pages, the exit status is 1, and the journal holds no record of this command

#### Scenario: Write error
- **WHEN** writing `nr_hugepages` or reading it back fails with an OS error, and the previous count can be written back
- **THEN** the command fails with exit status 1 naming the error, and the journal holds no record of this command; if writing back fails too, the record stays

#### Scenario: Restore after a shortfall
- **WHEN** the libvirt hook runs `restore j` after that failure, and a static pool of 4 pages existed before
- **THEN** the pool still holds 4 pages

### Requirement: Page size, amount and node are validated at parse time
`<pagesize>` SHALL be mandatory and a number with a `K`, `M` or `G` suffix
(case-insensitive, optional `B`); a size the kernel does not offer SHALL be a usage error
listing the available sizes. `<amount>` SHALL be mandatory, use the same notation, be
greater than zero and be an exact multiple of the page size, else a usage error.
`--node` SHALL take exactly one NUMA node in the form `N<n>` that has a pool of that
size, else a usage error (listing the nodes that have one, if the node has none).

#### Scenario: Unsupported size
- **WHEN** `hugepages 4M 8M` runs on a host offering 2M and 1G
- **THEN** it fails before any change with a usage error listing `2M 1G`

#### Scenario: Swapped arguments
- **WHEN** `hugepages 16G 2M` runs
- **THEN** it fails with a usage error that `16G` is not an available page size

#### Scenario: Amount not a multiple
- **WHEN** `hugepages 2M 3M` runs
- **THEN** it fails with a usage error `3M is not a multiple of 2M`

#### Scenario: Amount zero
- **WHEN** `hugepages 2M 0` runs
- **THEN** it fails with a usage error

#### Scenario: Size forms
- **WHEN** `<pagesize>` is `2M`, `2048k`, `2048KB` or `1g`
- **THEN** they select the 2M, 2M, 2M and 1G pools

#### Scenario: Node form
- **WHEN** `--node N0-1` or `--node 0` is given
- **THEN** it fails with a usage error (`--node takes exactly one node, e.g. N0`, or that the node needs the N form)
