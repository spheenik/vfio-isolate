# vfio-isolate

Python CLI (click) for isolating CPUs/memory on Linux hosts running VFIO VMs: cpusets
(cgroups v1 and v2), IRQ affinity, CPU governor, drop caches, compact memory, moving tasks.
Published on PyPI as `vfio-isolate`; entry point `vfio_isolate:run_cli`.

## Layout
- `vfio_isolate/cli.py` — click group with `chain=True`; each subcommand queues an
  action on the `Executor`, which runs them in order. `-u <file>` pickles the undo
  steps (reversed) for `restore`.
- `vfio_isolate/action/` — one `Action` subclass per command, all classmethods:
  `can_execute`, `execute`, `record_undo` (yields `Execution`s). New command = new
  action + register in `action/__init__.py` + click command in `cli.py` + README.
- `cpuset.py` (cgroup v1/v2 handling), `cpu.py`, `irq.py`, `nodeset.py` (C/N nodeset
  types, e.g. `C0-3,8`, `N0`).
- `nodeset_parser.py` is **generated** from `nodeset.lark` by `./build_parser`
  (needs `lark`, dev extra). Don't hand-edit it.

## Conventions
- No test suite. Changes touch `/sys` and `/proc`, so real runs need root.
- Release: bump `version` in `setup.py`, commit as `V x.y.z: <summary>`, build sdist
  into `dist/`, upload to PyPI.
- README documents every command and the example scripts; keep it in sync.
