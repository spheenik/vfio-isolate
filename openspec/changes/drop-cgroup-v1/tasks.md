## 1. Packaging and test scaffolding

- [ ] 1.1 Add `pyproject.toml` (setuptools backend, `requires-python >=3.9`, version `0.6.0.dev0`, extras `dev`/`test`, `vfio-isolate` console script, classifiers 3.9–3.14, explicit `packages.find include = ["vfio_isolate*"]`); delete `setup.py`
- [ ] 1.2 Verify `pip install -e '.[test]'` in a fresh venv in the scratchpad (not the stale `venv/`, `build/`, egg-info) and that `vfio-isolate --help` runs

## 2. Configurable filesystem root

- [ ] 2.1 Add `vfio_isolate/fsroot.py` with module attribute `ROOT = "/"` and `path(*parts)` (reads `ROOT` per call, strips leading slashes before joining)
- [ ] 2.2 Route every hard-coded `/sys` and `/proc` path through it: `cpu.py`, `irq.py`, `nodeset.py`, `action/drop_caches.py`, `action/compact_memory.py`, `action/cpu_governor.py` if applicable
- [ ] 2.3 Add `tests/conftest.py` with the `fake_host` fixture (mounts, cgroup tree, cpu/node sysfs, cgroup-cache reset) and layout helpers (pure v2, hybrid, v1-only, no-cpuset, cgroup2 at non-standard path)

## 3. cgroup v2-only backend

- [ ] 3.1 Implement mount detection from `<proc>/self/mounts` and the `cpuset` controller check as a cached `cgroup_root()` raising `HostUnsupportedError` (message mentions 0.5.x for v1 users)
- [ ] 3.2 Remove the import-time `setup()`; make `CPUSet` resolve paths via `cgroup_root()`
- [ ] 3.3 Delete `CGroupV1`; fold `CGroupV2` methods into `CPUSet`; delete the v1 flag getters/setters (existing v2 behaviour otherwise unchanged)
- [ ] 3.4 Tests: each `cgroup-backend` scenario (pure v2, non-standard mount, hybrid, no cgroup2, no cpuset controller)

## 4. Executor validation and CLI

- [ ] 4.0 Move `Executor` to module level; add `main(argv=None) -> int` (parse with `standalone_mode=False`, then run; show `click.ClickException` as click does, handle `click.exceptions.Exit`, map `HostUnsupportedError` to stderr + 1); `run_cli()` = `sys.exit(main())`
- [ ] 4.1 Add `needs_cgroup` class attribute to `Action` (default False) and set it on CPUSetCreate, CPUSetModify, CPUSetDelete, MoveTasks
- [ ] 4.2 `Executor.run()` and `restore` call `cgroup_root()` before the first execution when any queued action needs it (the error is mapped to exit 1 by `main()`, see 4.0)
- [ ] 4.3 Remove the four v1 flag options (long, `--no-`, short forms) from `cpuset-create`/`cpuset-modify` and the corresponding `CPUSetModify.Param` fields and undo records
- [ ] 4.4 Tests via `main([...])` + `capsys`: help works on a host without cgroup2; `drop-caches` alone works on a v1 host; mixed chain on unsupported host makes no change; removed option is a usage error with no change; `cpuset-modify --cpus/--mems` writes the files; help text has no "cgroup v1"

## 5. Documentation

- [ ] 5.1 README: remove the two cgroup v1 example sections and the v1 feature table; state cgroup v2 is required and point v1 users to 0.5.2
- [ ] 5.2 Update `CLAUDE.md` (layout, `fsroot`, how to run tests)
- [ ] 5.3 `openspec validate drop-cgroup-v1 --strict` passes; full pytest suite passes
