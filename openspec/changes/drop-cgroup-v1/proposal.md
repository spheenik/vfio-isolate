## Why

cgroup v1 is gone from the platforms vfio-isolate targets: systemd 258 removed it,
and kernels since 6.12 can be built without v1 cpusets. The v1 backend can no longer
be tested on a current system. It also shows signs of having no users: all four v1
flag getters have always returned True, so restore turned those flags on, and nobody
reported it. Dropping it now lets v0.6 be designed around cgroup v2 alone. This change
also fixes the cgroup detection and lays the testing foundation the later v0.6 changes
build on.

## What Changes

- **BREAKING**: Remove the cgroup v1 backend (`CGroupV1`, the `tasks` file, the v1 flag files).
- **BREAKING**: Remove the v1-only options from `cpuset-create` and `cpuset-modify`:
  `--cpu-exclusive`, `--mem-exclusive`, `--mem-migrate`, `--sched-load-balance`, and
  their short forms. On v2 these were accepted and silently ignored.
- **BREAKING**: On a system without a usable cgroup v2 cpuset hierarchy (v1 or hybrid
  layout, cgroup2 not mounted), commands that touch cpusets fail with a clear error
  instead of acting on the wrong hierarchy.
- Detect the hierarchy from `/proc/self/mounts`, finding the cgroup2 mount instead of
  taking the first mount whose type starts with "cgroup". Do it lazily, so `--help`
  and commands that don't touch cgroups work everywhere.
- Make the filesystem roots (`/sys`, `/proc`) configurable, so tests can point the
  tool at a fake tree.
- Add a pytest setup with a fake sysfs/procfs fixture, plus tests for detection and
  the remaining cpuset backend.
- Packaging: replace `setup.py` with `pyproject.toml`, set a correct
  `requires-python`, update the classifiers, and add a `test` extra.
- README: remove the v1 sections and state that cgroup v2 is required.

## Capabilities

### New Capabilities
- `cgroup-backend`: how vfio-isolate finds and validates the cgroup v2 hierarchy, what
  it requires of the system, and how it fails when those requirements aren't met.
- `cpuset-commands`: the options `cpuset-create` and `cpuset-modify` accept (the
  v2-only option surface).

### Modified Capabilities
(none — no specs exist yet)

## Impact

- Code: `vfio_isolate/cpuset.py` (v1 class removed, detection rewritten, no import-time
  side effect), `vfio_isolate/cli.py` (options removed),
  `vfio_isolate/action/cpuset_create.py`, `cpuset_modify.py`, `cpuset_delete.py`
  (flag params and undo of those flags removed).
- Undo files written by 0.5.x contain the removed flag fields and will not restore
  under 0.6. The undo format is replaced in the later `undo-journal` change anyway.
- Packaging: `setup.py` → `pyproject.toml`. New dev dependency: pytest.
- Users still on cgroup v1 have to stay on 0.5.2.
