## Context

See proposal.md for the motivation. Current mechanics (`vfio_isolate/cli.py`):
- `Executor.run()` does, per action: `record_undo(params)` (a generator of `Execution`s,
  which reads current state), then `execute(params)`.
- All undo `Execution`s go into one flat list, which is pickled **reversed** at the end.
- `restore` unpickles that list at queue time and queues it as a normal chain.
- `Executor.add` uses `serialize.unserialize` to turn click kwargs, which are already
  typed objects, into Params.

The order bug comes entirely from that global reversal. Each action already yields its
undo steps in the order they must be applied: `CPUSetDelete` yields create then modify,
and a full IRQ mask yields add then mask. Reversing the whole list flips the steps
inside each action. The fix is to reverse actions, not steps.

Param types that must survive serialization: `str`, `CPUNodeSet`, `NUMANodeSet`,
`IRQ` (has `.number`), `CPU` (has `.number`), `IRQAffinityOperation` (Enum, whose
`mask` value is accidentally a tuple `(1,)`). Any field may be `None`.

`irq-affinity` and `cpu-governor` queue one action per IRQ or CPU. This host has 124
IRQs and 32 CPUs, so a typical `prepare` is about 160 actions.

## Goals / Non-Goals

**Goals:**
- A write-ahead journal: crash-safe, correctly ordered, plain data, safe to reuse.
- `restore` that is resumable after a partial failure.

**Non-Goals:**
- Changing *what* individual actions record. Known semantic gaps stay for
  `cgroup2-cpuset`: `MoveTasks` undo moves back every task, including ones that were in
  the target before, and cpuset undo captures `cpuset.cpus.effective`.
- Failures that are swallowed today. `IRQ.set_affinity` and `CPUSet.add_pid` catch
  `OSError` and only log it with `-d`, so restore can't report them. Making them visible
  is `error-reporting`.
- General error presentation: tracebacks for unrelated errors, the root check.
- The README's suggested journal location (`readme-and-tests`).

## Decisions

### 1. JSON Lines, one record per action
```
{"format": "vfio-isolate-undo", "version": 1}
{"undo": [{"action": "cpuset-create", "params": {"cpuset_name": "/a"}},
          {"action": "cpuset-modify", "params": {"cpuset_name": "/a", "cpus": "2-3", "mems": "0"}}]}
```
- Line 1 is the header.
- Each further line is one executed action's undo steps, in apply order.
- An action that yields no undo steps writes no record.
- Restore reads the records, reverses them, and flattens.

Appending a later run's records gives exactly the "unwind every run newest-first"
semantics in the spec, with no special casing.

*Why JSONL*: appending one line per action plus `fsync` makes it write-ahead with no
rewriting. A crash mid-append leaves a truncated last line. That record belongs to an
action that hadn't started executing, so a truncated **last** line is dropped with a
warning. An unparsable line elsewhere is corruption, and the file is rejected.
*Alternative*: one JSON document rewritten atomically (tmp + rename) after each action.
That is equally safe, but costs O(n²) writes over 160 actions and more code.

### 2. Stable action names and a typed JSON codec
- Each Action gets `name` (the CLI command name: `cpuset-create`, `irq-affinity`, ...).
  `action/__init__.py` exposes a registry `ACTIONS = {name: cls}`.
- New `journal_codec` functions `encode(execution) -> dict` and
  `decode(dict) -> Execution`, driven by the Param dataclass field types:
  - `CPUNodeSet` and `NUMANodeSet` → list-form string;
  - `IRQ` and `CPU` → int;
  - Enum → member name;
  - `str`, `int`, `bool` and `None` pass through.
- Unknown action names, unknown or missing fields, and unsupported types all raise
  `JournalError`.
- `Executor.add`'s kwargs-to-Param path stays separate. It handles typed objects from
  click, not JSON, and gets simplified to `Param(**kwargs)` where possible.

*Why*: the class and module names stay free to change, and decoding can only ever build
known Params. That gives the "no arbitrary code" requirement.

### 3. Executor loop: `can_execute` → `record_undo` → append → `execute`
For each queued action:
1. `can_execute(params)`. A false result raises `PreconditionError(message)`, which is
   reported and gives exit 1, and nothing is recorded for it. Implemented for
   `CPUSetCreate` (target must not exist) and for `CPUSetModify`, `CPUSetDelete` and
   `MoveTasks` (named cpusets must exist). The default stays True.
2. `steps = list(record_undo(params))`. Fully materialized before anything is written.
3. If `-u` is given and steps is non-empty, append the record, then `flush` +
   `os.fsync`.
4. `execute(params)`.

If 2 raises, nothing is written for that action and the run stops. If 4 raises, the
record stays. That is safe because every undo step sets absolute values captured
beforehand, plus two tolerances that apply to every `execute`:
- `CPUSetCreate.execute` succeeds if the cpuset already exists (undo of a delete that
  failed before `rmdir`).
- `CPUSetDelete.execute` succeeds if the cpuset is already gone (undo of a create that
  failed before `mkdir`).

User-issued commands still fail on these cases through step 1. Restore does not call
`can_execute`, because undo steps are applied as recorded.

### 4. Opening the journal for recording
Done at the start of `run()`, before any action, as part of the up-front validation:
- `os.open(path, O_RDWR|O_CREAT|O_APPEND|O_NOFOLLOW|O_CLOEXEC, 0o600)`.
  `O_NOFOLLOW` gives `ELOOP` on a symlink, including a dangling one.
- `fstat`: must be a regular file owned by `geteuid()` with no group/other write bit.
  Otherwise `JournalError`.
- If size is 0 (we just created it, or it's empty), write the header. Otherwise read
  and validate the header line through the open fd. Anything else → `JournalError`,
  file untouched.

No `O_EXCL` is needed, because appending to an existing journal is the intended
behaviour. The ownership and mode check is what makes trusting a pre-existing file
safe.

### 5. Restore: decoded at queue time, applied by the Executor
- The click callback for `restore` reads, validates and fully decodes the file
  immediately (open with `O_NOFOLLOW`, same `fstat` checks, header/version,
  pickle detection, decode all steps). Problems raise `JournalError` from the callback.
  Click parses the whole chain before `run()`, so nothing in the chain has run yet.
  This also gives the existing `test_restore_checked_before_executing` behaviour.
- It queues one `RestoreBatch(path, records)` item. The Executor's up-front cgroup
  pre-check includes the steps inside it.
- When the Executor reaches the batch, it applies records newest-first, steps in
  order. Each step is wrapped in try/except, and a failure is printed to stderr as
  `restore: <action> <params>: <error>`. The failed steps are kept, grouped by their
  original record.
- All OK → `os.unlink(path)`. Otherwise write the header plus the failed records to a
  temp file in the same directory (0600, `O_EXCL`) and `os.replace` it over `path`, so
  the run exits 1.
- A chain with both `-u` and `restore` is a usage error, because restore never records.

### 6. Pickle detection without unpickling
`pickle` is no longer imported anywhere in the package. A 0.5.x file is a pickled list,
so it starts with `\x80` (protocols 2–5) or `(`/`]` (protocols 0–1). Those first bytes
give the 0.5.x message. Any other non-header content gives "not a vfio-isolate undo
journal".

## Risks / Trade-offs

- [About 160 `fsync`s per `prepare`] → On tmpfs (`/run`, and `/tmp` on most distros)
  fsync is nearly free. On a disk-backed path it is roughly 0.1–10 ms each, so up to
  about 1.5 s in the worst case. `readme-and-tests` moves the recommended location to
  `/run`. If that proves too slow, batch one record per CLI command (all of its
  actions' undo first, then execute them); that keeps the format unchanged.
- [Appending means a journal that is never successfully restored grows] → Only a
  failed `restore` or an unreleased VM leaves it in place, and each run adds one
  record per action. A successful restore deletes it.
- [A journal edited by root by hand can still contain harmful but valid steps, such as
  deleting a cpuset] → No worse than running the tool by hand. The ownership and mode
  checks keep other users out.
- [Swallowed IRQ and task-move errors mean restore can report success while a step did
  nothing] → Known; see Non-Goals.

## Migration Plan

Release notes: "Release any VM prepared with 0.5.x (run its `restore`) before
upgrading. 0.6 refuses 0.5.x undo files."
