## Why

Undo is the core promise of vfio-isolate (`prepare` with `-u`, `release` with `restore`),
and today it is unreliable in several ways:
- Every multi-step undo comes back in the wrong order. That breaks undoing
  `cpuset-delete` and gives wrong IRQ affinities.
- The file is only written after every action succeeded, so a failure halfway leaves
  changes with no undo.
- A second `prepare` overwrites the original state.
- `restore` stops at the first failure.
- The file is a pickle that root loads, from a path the README puts in `/tmp`.

## What Changes

- **BREAKING**: The undo file becomes a JSON Lines journal with a format header. Pickle
  undo files from 0.5.x are detected and refused, with a message telling the user to
  finish with 0.5.2.
- Before each action runs, its undo steps are appended to the journal and flushed to
  disk. A failure or crash part-way leaves a journal that undoes exactly what may have
  been changed.
- Each action's undo steps are stored in the order they must be applied. Restore
  replays actions newest-first and each action's steps in stored order. This fixes the
  `cpuset-delete` and IRQ-affinity undo bugs.
- If the undo file already exists, the run appends to it. Restore then unwinds every
  recorded run, newest-first, back to the state before the first one. That is correct
  for a double `prepare`, a `prepare` retried after a partial failure, and a `prepare`
  after a partially failed `restore`.
- `restore` attempts every step and reports each failure. On full success it deletes
  the journal. If any step failed it rewrites the journal with only the failed steps
  and exits non-zero, so a later `restore` can retry.
- Actions check their preconditions before their undo is recorded. For example,
  `cpuset-create` on an existing cpuset fails without recording a delete of it.
- The journal is created with mode 0600 and is never followed through a symlink. A
  journal that isn't owned by the current user, or is writable by others, is refused.
- A journal named by `restore` is read and validated before anything in the chain runs.
- Restore treats "create a cpuset that already exists" and "delete a cpuset that's
  already gone" as success, so the undo of a partly failed action is always safe.

## Capabilities

### New Capabilities
- `undo-journal`: recording undo information during a run, the file's format and safety
  properties, and how `restore` replays it.

### Modified Capabilities
(none)

## Impact

- Code: `vfio_isolate/cli.py` (Executor, `restore`), `vfio_isolate/serialize.py`
  (JSON codec replaces the dataclass helper), `vfio_isolate/action/*` (stable action
  names, `can_execute` preconditions), tests.
- Undo files written by 0.5.x can't be restored by 0.6. A VM prepared with 0.5.x must be
  released with 0.5.x before upgrading. Release notes must say so.
- README: describe the journal behaviour. Moving the suggested path from `/tmp` to
  `/run` is done in `readme-and-tests`.
