# vfio-isolate

Python CLI (click) for isolating CPUs/memory on Linux hosts running VFIO VMs: cpusets
(cgroup v2 only), IRQ affinity, CPU governor, drop caches, compact memory, moving tasks.
PyPI `vfio-isolate`, entry point `vfio_isolate:run_cli`. Behavior is specified in
`openspec/specs/` (OpenSpec; plans in `openspec/changes/`); user docs in README.md,
breaking changes in CHANGELOG.md.

## Layout
- `cli.py` — click group, `chain=True`; commands only queue actions on the `Executor`
  (so all validation happens before anything runs). `main(argv) -> int` is the testable
  entry. Per action: `can_execute` -> `record_undo` -> journal append+fsync -> `execute`.
  `main()` formats errors (command name, restore hint); Ctrl-C exits 130.
- `action/` — one `Action` subclass per command, classmethods `can_execute`, `execute`,
  `record_undo` (yields `Execution`s in the order they must be applied; restore reverses
  actions, never steps). Stable `name` = CLI command, registered in `ACTIONS`. New command =
  action + `ACTIONS` + click command + README section (a test checks the heading).
- `journal.py` — JSON Lines undo journal; 0.5.x pickle files are detected and refused.
  Never load pickles (the generated parser contains lark's pickle code; it is unused).
- `cpuset.py` — cgroup v2 only; lazy `cgroup_root()` raises `HostUnsupportedError`.
- `systemd.py` — `systemctl` only via `_run()`; `set_property()` uses `--runtime`.
- `nodeset.py` — CLI forms `C` list, `N` NUMA nodes, `M` hex mask (parsed in Python).
  `nodeset_parser.py` is generated from `nodeset.lark` by `./build_parser` (lark 1.1.5);
  don't hand-edit.
- `privileges.require_root()` runs first in `Executor.run` and the `restore` callback.
- `output.failures` collects per-item IRQ/task `OSError`s (errno table; never stops the run).
- `fsroot.py` — all `/sys` and `/proc` access MUST go through `fsroot.path(...)`.

## cpuset rules
- systemd units -> `systemctl set-property --runtime` (`daemon-reload` resets direct
  writes); other cgroups -> direct writes after enabling `cpuset` in ancestors.
- Empty = inherit; write `"\n"` (an empty write is a no-op). Undo uses configured values.
- Partitions (experimental): undo restores the previous type, never empty (empty
  `CPUSetPartition=` leaves `isolated invalid`; unset is restored as `member`), one
  `set-property` call with the old cpus. Direct writes: to `member` -> partition first, else
  cpus first. Kernel `invalid` read-back -> `PartitionInvalidError` (exit 1).

## Conventions
- `pyproject.toml` packaging. Tests: `pytest` (fixtures `fake_host`, `sd` fake systemd in
  `tests/conftest.py`; `require_root` patched). README `sh` blocks are parsed by
  `tests/test_readme.py`: no prompts, no space after `\`, only variables assigned in the block.
- VM suite (marker `vm`): `scripts/vm-test --venv <venv>`, ~10 s, guest boots
  `getty.target`. Never run anything as root on the host.
- Release: bump `version` in `pyproject.toml`, update CHANGELOG.md, commit
  `V x.y.z: <summary>`, build sdist into `dist/`, upload to PyPI.
