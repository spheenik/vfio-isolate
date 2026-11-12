## Context

Hugepage pools live in `/sys/kernel/mm/hugepages/hugepages-<kB>kB/` (system-wide) and
`/sys/devices/system/node/node<N>/hugepages/hugepages-<kB>kB/` (per node). Each has
`nr_hugepages`, `free_hugepages`, `resv_hugepages`, `surplus_hugepages`. Undo records are written to the journal before the
action runs.

## Decisions

### Relative counts, relative undo
`hugepages 2M 16G` adds 8192 pages to whatever the pool holds; undo releases 8192. An absolute undo
("set back to the old value") breaks with two VMs whose start and stop overlap: VM A
records 0, VM B records 8; if A stops first and B second, the pool ends at 8 and the
memory is lost until someone notices. Relative release is correct in any stop order.
Releasing never harms a running VM: the kernel keeps in-use and reserved pages as surplus
and frees them when the VM exits (VM probe).

Release: target = max(current − count, 0). A read-back above the target is success (the
kernel kept pages that are still in use).

### Shortfall: roll back, then drop the journal record
The undo record is written before the allocation, so it cannot know how many pages the
kernel will hand out. Options considered:
- Release `count` regardless: after a shortfall, restore releases pages this run never
  added, for example from a static boot-time pool another VM relies on. Rejected: a
  static 1G pool cannot be rebuilt at runtime.
- Never release below the pre-value: exact for a shortfall, but leaks when overlapping
  VMs stop in the wrong order. Rejected.
- Chosen: on a shortfall `execute` writes `nr_hugepages` back to the pre-value (giving
  back the k pages it got) and raises `RolledBackError`. The Executor catches that type,
  truncates the journal to the offset before the action's record, and re-raises. Restore
  then has nothing to release for it. Undo stays a plain relative release.

`RolledBackError` subclasses `PreconditionError`, so error formatting and exit code are
unchanged. The restore hint counts only records still in the journal; if the rolled-back
action was the first to change anything, the message says that nothing was changed.

Messages: `hugepages failed: got 2G of 6G in 1G pages on node N0; the pages were released`
for a shortfall (amounts in the largest exact unit), and `hugepages failed: could not add
6G in 1G pages on node N0: <error>; nothing was kept` when the write or read-back raises `OSError` and the pre-value could be
written back. If that write-back fails too, the original `OSError` propagates and the
journal record stays.

### Serialized runs
Adding is read, write, read back; two concurrent runs could both read 0, write 8 and
both "succeed" with 8 pages in total. `Executor.run` (including `restore`) holds an
exclusive `flock` on `/run/vfio-isolate.lock` (via `fsroot.path`, so tests use the fake
tree), waiting for it. This also covers other read-modify-write commands
(`irq-affinity add`).

### Page size, amount and node
`hugepages [--node N<n>] <pagesize> <amount>`, for example `hugepages 1G 16G`.
- `<pagesize>`: mandatory. `<n>K|M|G` with optional `B`, case-insensitive (`2M`, `2048k`,
  `1G`, `1GB`); converted to kB. Validated when the command line is parsed against the
  existing `hugepages-<kB>kB` directories; the error lists available sizes in human form
  (`'16G' is not an available page size; available: 2M 1G`). There is no default size: the
  size must match the VM's (libvirt `<page size=...>` in `<memoryBacking>`), so the user
  names it. A swapped call (`16G 2M`) fails as an unavailable page size.
- `<amount>`: mandatory, same parser, greater than zero and an exact multiple of the page
  size (`16G is not a multiple of 1G`). The command converts it to a page count; the
  action Param keeps `count`, so the journal format is unchanged.
- `--node N<n>`: parsed with the NUMA nodeset parser of `--mems` (N form only); exactly one
  node (`--node takes exactly one node, e.g. N0`), a bare number is rejected. The node must
  have a pool of that size, else a usage error listing nodes that do (`N0 N1`).

### Module layout
`vfio_isolate/hugepages.py`: `pool_dir(size_kb, node)`, `read_count`, `write_count`,
`available_sizes()`, `parse_size()`, `format_size()`. All paths via
`fsroot.path`. Action `HugePages` (name `hugepages`) in `action/hugepages.py` with Param
`size_kb: int`, `node: Optional[int]`, `count: int`, `release: bool` (the undo is the
same action with `release=True`).

## Risks

- 1G pages at runtime are unreliable on a long-running host; the command reports it
  rather than fixing it. Host test 2026-11-12: 0 of 8 1G pages after 11 h uptime;
  `hugetlb_cma=` reserved and allocated fine, but VFIO cannot pin CMA pages, so the
  VM did not start. README recommends 2M at runtime, 1G only as a boot reservation.
- A signal during the add: in a VM probe, SIGINT and SIGTERM sent while 1700 2M pages
  were being allocated did not cut the allocation short; the kernel finished it, the
  process exited 130/143, and the journal record matched the pool. Whether a fatal signal
  can cut a 1G allocation short (contiguous-range allocation) is untested; then a restore
  would release up to `count` pages, more than were added.
- The lock serializes vfio-isolate runs only; another tool writing `nr_hugepages`
  concurrently is not covered.
