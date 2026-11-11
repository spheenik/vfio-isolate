## Context

See proposal.md for the motivation. Current state of the code:

- `vfio_isolate/cpuset.py` has a `CPUSet` facade that hands every operation to
  `CPUSet.impl`, which is either `CGroupV1` or `CGroupV2`. A module-level `setup()`
  runs at import time. It takes the first mount whose type starts with "cgroup", as
  reported by `psutil.disk_partitions`, and raises if none is found. Because `cli.py`
  imports this, even `--help` depends on it.
- Absolute `/sys` and `/proc` paths are hard-coded in `cpu.py`, `irq.py`, `nodeset.py`,
  `drop_caches.py` and `compact_memory.py`, and the cgroup mount point is used as-is.
- `cli.py` runs `click.group(chain=True)`. Click parses the whole chain first, each
  command only queues an `Execution` on the `Executor`, and `Executor.run()` executes
  them in order afterwards. So there is a natural point to validate everything before
  any change is made.
- There are no tests, and packaging is `setup.py` only.

## Goals / Non-Goals

**Goals:**
- A single v2 code path with no implementation indirection.
- Host validation that runs once, before execution, and only when the chain needs it.
- Every filesystem access is relative to a configurable root, so the test suite (and
  the later changes) can run against a fake tree without root.

**Non-Goals:**
- Fixing v2 cpuset semantics: the controller-enable check, effective vs. configured
  CPUs, partitions, and systemd AllowedCPUs. All of that belongs to `cgroup2-cpuset`.
  The existing v2 behaviour moves over unchanged.
- The undo format (`undo-journal`) and general error reporting such as the root check
  and BadParameter (`error-reporting`). The only error handled here is the
  host-validation error.
- Integration tests in a VM (`readme-and-tests`).

## Decisions

### 1. Read `/proc/self/mounts` directly instead of psutil
Parse `<proc>/self/mounts`. Reject the host if any `cgroup` (v1) mount has `cpuset` in
its options. Otherwise use the `cgroup2` mount, preferring `/sys/fs/cgroup` when there
are several. Option and controller matching is by whole token, never by substring. Then require
`cpuset` among the space-separated tokens of the root's
`cgroup.controllers`.
*Why*: psutil hides the mount options, which we need to see where cpuset is bound, and
it can't be pointed at a fake root. With this, psutil is only needed for process names
in `add_pid`.
*Alternative*: `stat -f` / `statfs` magic numbers. That gives the fs type but not the
controller binding, and it is harder to fake.

### 2. Lazy, cached hierarchy, validated by the Executor
`cpuset.py` gets a `cgroup_root()` function that detects and validates on its first
call, caches the result, and raises `HostUnsupportedError(message)`. Actions declare
`needs_cgroup = True` as a class attribute (on CPUSetCreate, CPUSetModify,
CPUSetDelete and MoveTasks). `Executor.run()` calls `cgroup_root()` once before the
first execution if any queued action needs it. `restore` does the same for the
executions it loads. `run_cli()` catches `HostUnsupportedError`, prints the message
to stderr and exits 1.
*Why*: it meets the spec's "before any change" requirement for whole chains, and
`--help` never touches cgroups. Checked: `Executor.add` and `restore` only queue, and
parse-time callbacks read `/proc/irq` and CPU/node sysfs but never cgroup files.

To make this testable, `Executor` moves out of `run_cli()` to module level, and a
`main(argv=None) -> int` entry point does parse → run. It also catches
`click.ClickException`/`click.exceptions.Exit` and shows them the way click normally
does (usage errors print a message instead of a traceback, `--help` exits 0), and
turns `HostUnsupportedError` into stderr + exit 1. `run_cli()` becomes
`sys.exit(main())`.
*Alternative*: validating inside each action's `execute`. That would let `drop-caches`
run before a later cpuset command fails.

### 3. A single `fsroot` module for all system paths
Add `vfio_isolate/fsroot.py` with a module attribute `ROOT = "/"` and
`path(*parts) -> str`, which joins onto it. `path` reads `ROOT` on every call, so tests
monkeypatch the attribute and need no module reloads. Every hard-coded path goes
through it. The mount point from `/proc/self/mounts` is joined onto it too, so a fake
`mounts` file listing `/sys/fs/cgroup` resolves into the fake tree. Leading slashes
are stripped before joining, because `os.path.join(root, "/sys")` would discard `root`.
*Why*: one mechanism for all modules. Later changes (IRQs, governor, undo) get a
testable surface without more refactoring.
*Rejected*: a `VFIO_ISOLATE_ROOT` environment variable. The tool runs as root, so an
env var would give production a way to redirect writes, and the in-process tests
don't need one.
*Alternative*: dependency-injecting a root into every class. That is cleaner in
theory, but it spreads through every constructor and action Param for no gain in a
CLI tool.

### 4. Fold `CGroupV2` into `CPUSet`
Delete `CGroupV1`, move the `CGroupV2` methods into `CPUSet`, and delete the eight
v1 flag getters and setters. Drop the four flag fields from `CPUSetModify.Param` and
the CLI.
*Why*: indirection with a single implementation is just noise.

### 5. Packaging: pyproject.toml with the setuptools backend
Use `requires-python = ">=3.9"` (RHEL 9's system Python is the oldest still-relevant
target; the code needs dataclasses and f-strings). Version `0.6.0.dev0`. Package discovery is explicit
(`[tool.setuptools.packages.find] include = ["vfio_isolate*"]`), because flat-layout
auto-discovery fails with `openspec/`, `tests/`, `venv/` and `build/` at the top level. Extras:
`dev = ["lark>=1.1.5"]`, `test = ["pytest>=7"]`. Keep the `vfio-isolate` console
script. Delete `setup.py`.
*Alternative*: hatchling or uv_build. Either would work. setuptools keeps the diff
minimal and needs no new tooling.

### 6. Test layout
`tests/conftest.py` provides a `fake_host(tmp_path, monkeypatch)` fixture. It builds
`proc/self/mounts`, a `sys/fs/cgroup` tree (`cgroup.controllers`,
`cgroup.subtree_control`, `cpuset.cpus[.effective]`, `cpuset.mems[.effective]`,
`cgroup.procs`, and child dirs created on demand), plus `sys/devices/system/{cpu,node}`.
It monkeypatches `fsroot.ROOT` and resets the cgroup cache. Helpers switch the host to a
hybrid, v1-only or no-cpuset layout. CLI tests call `main([...])` and use pytest's `capsys` for output, so that execution,
exit codes and "no change made" are all covered.

The fake tree has one limit: `os.mkdir` in a normal directory doesn't populate the
cgroup files the way the kernel does. Tests that create cpusets call a fixture helper
that adds those files after the mkdir; the production code is not patched.
Kernel semantics stay untested until the VM suite exists.

## Risks / Trade-offs

- [Undo files from 0.5.x carry the removed Param fields] → They still unpickle (pickle
  restores `__dict__`) and `execute` ignores the extra fields, so cpus/mems are
  restored but the removed flags are not. Accepted. The undo format is replaced in
  `undo-journal` anyway. Say so in the release notes.
- [Fake-tree tests can pass while the real kernel rejects a write] → Known gap,
  covered later by the VM suite. Keep the fixtures minimal so they don't encode wrong
  kernel behaviour.
- [Some v2 host has cgroup2 at a non-standard path and another, irrelevant cgroup2
  mount] → Prefer `/sys/fs/cgroup`, otherwise the first one. That is good enough;
  multi-mount setups are exotic.
