## 1. VM runner

- [x] 1.0 (done before apply) pre-apply probes answered (design.md "Probe results") and specs/design updated
- [ ] 1.1 Write `scripts/vm-test` per design.md probe 6 (vng --systemd, --rwdir for the venv, venv path as argument/env, waits for systemd, runs `pytest -m vm tests/vm`, propagates exit code via a result file in the rwdir since vng's own exit code may not reflect the guest command)
- [ ] 1.2 Add the `vm` marker, default `-m "not vm"` in pytest config, and `tests/vm/test_smoke.py` (systemd is PID 1, cgroup2 with cpuset, `systemctl show system.slice` works); `scripts/vm-test` passes

## 2. systemd module

- [ ] 2.1 `vfio_isolate/systemd.py`: `systemd_running()`, `unit_for_cgroup()`, `show()` (space-separated lists normalised to commas), `set_property(--runtime)` (all properties in one call), `supports()`, all `systemctl` calls through one `_run()`
- [ ] 2.2 Fake systemd in `tests/conftest.py` (opt-in on `fake_host`): `/run/systemd/system`, unit table with ControlGroup and properties, mirrors AllowedCPUs/AllowedMemoryNodes/CPUSetPartition into the fake cgroup tree, records calls
- [ ] 2.3 Unit tests for detection, unit resolution (match, not loaded, mismatch), show/set parsing, supports()

## 3. cpuset core

- [ ] 3.1 Remove the broken controller check and all writes from getters; add `ensure_controller_path()` (ancestors only) used by `create()` and direct-path setters
- [ ] 3.2 Nodeset: empty check after rstrip (`"\n"` → empty set); empty values written as `"\n"`; fake tree's inheriting cgroups hold `"\n"` (mkcg option)
- [ ] 3.2a Add configured readers (`cpuset.cpus`, `cpuset.mems`, `cpuset.cpus.partition` with invalid normalisation) and a partition setter with read-back raising `PartitionInvalidError`
- [ ] 3.3 Codec: support `Optional[...]` and `List[int]`; missing fields with dataclass defaults decode to the default; round-trip tests

## 4. Actions and CLI

- [ ] 4.1 `CPUSetModify`: `partition` field (member/root/isolated/None; empty recorded from systemd stored as member), None vs empty semantics, backend selection, write ordering, configured-state `record_undo` for both backends; `can_execute` rejections (`/`, CPUSetPartition unsupported)
- [ ] 4.2 `CPUSetCreate`/`CPUSetDelete`: reject `/` and systemd units; create also rejects a non-delegated systemd ancestor; `create()` without cpus/mems leaves them empty (inherit); `CPUSetDelete.record_undo` uses configured readers and captures partition
- [ ] 4.3 `MoveTasks`: `pids` field, record captured PIDs, execute moves only listed PIDs still in source
- [ ] 4.4 CLI: `cpuset-modify --partition [member|root|isolated]` marked experimental in help; `main()` maps `PartitionInvalidError` to exit 1
- [ ] 4.5 Fake-tree tests for every `cpuset-management` scenario that the fake can express (systemd route, undo of properties, unit mismatch, controller path, reads never write, inheriting cgroup, partition invalid + restore, partition undo order, move-tasks undo, structural rejections) and the `cpuset-commands` scenarios; mark in each test's docstring whether it is fake-only (systemd scenarios prove only the systemctl arguments) or also covered in tests/vm; mutation-check the undo-order and move-tasks tests

## 5. VM tests

- [ ] 5.1 `tests/vm/`: direct-path inherit round trip (empty cpuset.cpus restored, effective = parent's), systemd route + effective cpus, daemon-reload persistence, undo resets AllowedCPUs, direct create enables ancestor controller, isolated partition valid with unrestricted siblings (siblings' effective shrinks), partition undo via systemd and via direct path (reads member, siblings regain CPUs), direct write to a systemd slice reset by daemon-reload is NOT used by the tool (systemd route survives reload)
- [ ] 5.2 Run `scripts/vm-test`; all VM tests pass

## 6. Docs

- [ ] 6.1 README: systemd hosts are handled through unit properties; `--partition` (experimental) with an example restricting all top-level slices first; recommend slices over move-tasks on systemd; how to run the VM suite
- [ ] 6.2 Update `CLAUDE.md` (systemd.py, backends, VM suite)
- [ ] 6.3 `openspec validate cgroup2-cpuset --strict`, default pytest and `scripts/vm-test` pass
