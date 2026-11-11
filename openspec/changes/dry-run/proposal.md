## Why

A libvirt hook runs vfio-isolate where the user can't watch, and a wrong CPU list or
cpuset name shows up only as a VM that starts slowly or not at all. Users want to see
what a command line would do, and what `restore` would undo, without touching the host.

## What Changes

- New global option `-n/--dry-run`: the command line is parsed and validated as usual,
  preconditions are checked, and each action prints what it would do with current and
  new values. Nothing is written: no `execute`, no journal, no lock.
- Chains whose later steps depend on earlier ones (`cpuset-create /a` followed by
  `move-tasks / /a`) are handled by a small overlay of cpusets that earlier steps would
  create or delete; values that depend on an earlier step are printed as such.
- `restore -n <journal>` lists the undo steps it would apply, in order.
- Works without root where the files involved are readable; unreadable values are
  reported as unknown instead of failing.

## Capabilities

### New Capabilities
- `dry-run`: previewing a command line or a restore without changes.

## Impact

- Code: `cli.py` (option, Executor dry mode), `Action.describe` on every action, a
  dry-run context object passed to `describe`/`can_execute`.
- Tests: every README invocation run with `-n` on the fake host must leave the tree
  unchanged; per-action describe tests; a coverage test that every action in `ACTIONS`
  implements `describe`.
