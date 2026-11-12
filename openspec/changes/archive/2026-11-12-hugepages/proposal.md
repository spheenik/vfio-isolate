## Why

Two users asked for hugepage allocation (#2 in 2020, for virtiofs; #10 in 2022, who ran a
separate script for it). A VM backed by hugetlbfs pages needs them in the pool before it
starts, and freed afterwards so the RAM is usable again. vfio-isolate already prepares
the host with `drop-caches` and `compact-memory`; allocating the pages is the step that
follows, and it needs the same undo as everything else.

VM probes (kernel 7.2) showed what the command has to handle:
- Writing `nr_hugepages` succeeds even when the kernel allocates fewer pages than asked;
  only reading the value back shows the shortfall. 2M pages were allocated in full every
  time; 1G pages often only partially, varying per boot, and `compact-memory` did not
  help once kernel slab memory was fragmented.
- Lowering `nr_hugepages` below the pages in use or reserved keeps those pages (as
  surplus) and frees them when their user exits; a running VM's mapping is unaffected.

## What Changes

- New command `hugepages [--node N<n>] <pagesize> <amount>`: adds `<amount>` of memory in
  pages of `<pagesize>` (for example `hugepages 1G 16G`) to the pool, system-wide or on
  one NUMA node. Undo releases the same number of pages.
- If the kernel allocates fewer pages than asked, the command gives back the pages it got
  and fails with exit 1, naming how many it got. Its undo record is then removed from the
  journal, so a following `restore` does not release pages this run never added.
- Executor: an action that undid its own changes before failing has its journal record
  removed (generic mechanism, used by `hugepages` only for now).
- Runs of vfio-isolate are serialized with a lock, because adding pages is a
  read-modify-write of `nr_hugepages` and two VMs may start at the same time.
- README: `### hugepages` section, hook recipe, notes on 2M versus 1G pages.

## Capabilities

### New Capabilities
- `hugepages`: allocating and releasing hugepages with undo, shortfall handling.

### Modified Capabilities
- `undo-journal`: an action that rolled itself back leaves no record; runs are serialized.

## Impact

- Code: new `vfio_isolate/hugepages.py` (sysfs access, size parsing), new action
  `action/hugepages.py`, `cli.py` (command, lock, journal record removal), `journal.py`
  (remove the last appended record).
- Tests: fake hugepage pool with a capacity model in `tests/conftest.py`, unit tests, a VM
  test with 2M pages.
- Closes #2 and #10 at the release.
