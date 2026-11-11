# vfio-isolate

Python CLI (click) for isolating CPUs/memory on Linux hosts running VFIO VMs: cpusets
(cgroup v2 only), IRQ affinity, CPU governor, drop caches, compact memory, moving tasks.
Published on PyPI as `vfio-isolate`; entry point `vfio_isolate:run_cli`. cgroup v1 was
dropped in 0.6; v1 users stay on 0.5.2.

## Layout
- `vfio_isolate/cli.py` — click group with `chain=True`; each subcommand queues an
  action on the module-level `Executor`, which runs them in order. `main(argv) -> int`
  is the testable entry point. `-u <file>` pickles the undo steps (reversed) for `restore`.
- `vfio_isolate/action/` — one `Action` subclass per command, all classmethods:
  `can_execute`, `execute`, `record_undo` (yields `Execution`s). Actions that need
  cpusets set `needs_cgroup`. New command = new action + register in
  `action/__init__.py` + click command in `cli.py` + README.
- `cpuset.py` — cgroup v2 only; `cgroup_root()` is lazy/cached and raises
  `HostUnsupportedError` if the host has no v2 cpuset controller. Also `cpu.py`,
  `irq.py`, `nodeset.py` (C/N nodeset types, e.g. `C0-3,8`, `N0`).
- `fsroot.py` — `ROOT` + `path()`. All `/sys` and `/proc` access MUST go through
  `fsroot.path(...)` so tests can redirect it to a fake tree.
- `nodeset_parser.py` is **generated** from `nodeset.lark` by `./build_parser`
  (needs `lark`, dev extra). Don't hand-edit it.

## Conventions
- Packaging is `pyproject.toml` (no `setup.py`).
- Tests: `tests/`, with a `fake_host` fixture that simulates host layouts under a
  temp dir. Run: `pip install -e '.[test]'` then `pytest`. Real runs need root.
- Release: bump `version` in `pyproject.toml`, commit as `V x.y.z: <summary>`, build
  sdist into `dist/`, upload to PyPI.
- README documents every command and the example scripts; keep it in sync.
- Uses OpenSpec: proposals/plans in `openspec/changes/`, current specs in `openspec/specs/`.
