## Context

See proposal.md for motivation. Relevant current state:
- `cli.main(argv)` parses everything first (click `chain=True`; subcommand callbacks only
  queue actions on the `Executor`), then `Executor.run()` executes. So anything checked in a
  click callback is checked before any change.
- `IRQ.set_affinity` and `CPUSet.add_pid` swallow `OSError` and return `False`; actions are
  classmethods with no run context, so per-item reporting needs a run-wide sink.
- `main` maps known errors to one stderr line; everything else is a traceback.
- `nodeset.lark` has `list_form | mask_form` with `MASK_ENTRY.1` (exactly 8 hex digits)
  outranking `NUMBER`. Kernel files the code reads (`cpulist`, `smp_affinity_list`,
  `cpuset.*`, node lists) are all list form; mask form is used only for CLI input.

## Goals / Non-Goals

**Goals:** the behavior in the three delta specs; no new dependencies.

**Non-Goals:** localized messages; a machine-readable error output; making non-root runs
work through capabilities or delegated cgroups; README changes (readme-and-tests).

## Decisions

### Root check in `Executor.run`, behind a seam
`Executor.run()` calls `privileges.require_root()` first, before the cgroup check, opening
the journal or any action. That keeps `--help` and usage errors unprivileged, because
they never reach `run()`. The `restore` callback reads the journal at parse time, so it
calls `require_root()` first as well (otherwise a non-root user would see the journal
owner check instead). `require_root()` checks `os.geteuid() == 0` and is the single
seam tests patch (the `fake_host` fixture patches it to pass; one test unpatches it).
- Alternative: skip the check when `fsroot.ROOT` is redirected. Rejected: it couples
  production behavior to a test hook.
- Alternative: no check, report `EACCES` nicely. Rejected: the first action may succeed
  before a later one hits `EACCES`, leaving a half-applied host.

### Run-wide failure collector in `output.py`
`output.failures` is a collector reset by `main()` at start. `IRQ.set_affinity` and
`CPUSet.add_pid` call `failures.irq(number, err)` / `failures.task(pid, name, err)` from
their `except OSError` and still return `False`. The collector classifies by errno:

| item | errno  | kind (summary line)                         |
|------|--------|---------------------------------------------|
| IRQ  | EIO    | kernel-managed or not movable, kept affinity |
| IRQ  | ENOENT | gone                                        |
| task | EINVAL | kernel thread, not movable                  |
| task | ESRCH  | exited                                      |

Other errnos are printed on their first occurrence per (item type, errno) as
`vfio-isolate: warning: IRQ 45: <strerror>` (`task 1234 (name): ...`); later items with
the same errno are counted into a summary line (`... and 41 more tasks: <strerror>`). A
systematic failure (e.g. `EBUSY` on a destination with child controllers) is therefore
two lines, not one per task. Total failure is an error, though: the collector also counts
successes, and `Executor.run` scopes it per `irq-affinity`/`move-tasks` execution
(`begin()`/`end()`). An execution with ≥1 attempt, 0 successes and ≥1 unexpected errno
marks the run failed (exit 1, `<command>: no IRQ could be changed` / `no task could be
moved`); later actions still run. Expected-only failures (e.g. all kernel threads) stay
exit 0. `restore` steps are not scoped this way; restore already reports failed steps. `main()` prints the summary lines in a `finally`, so they also
appear when the run later stops on an error. `-v` adds the item lists (IRQ numbers; PID and
name). The same code paths run during `restore`, so restore gets the same reporting
without extra work.
- Alternative: return per-item results up through `execute()`. Rejected: changes the
  `Action` interface for two actions and `restore` would need to thread them through too.

### Stopping failures: `Executor` tracks progress, `main` formats
`Executor` keeps `current` (the action name being checked/recorded/executed, or `restore`),
`changed` (an action has started `execute`) and `undo_file`. `main()` catches, in order:
- `KeyboardInterrupt` (raised inside `run()`) and `click.exceptions.Abort` (click's
  conversion of Ctrl-C during parsing; no prompts are used, so it has no other source) →
  exit 130, with `vfio-isolate: interrupted during <current>` + hint, or
  `vfio-isolate: interrupted, nothing was changed` when `current` is still `None`;
- the existing known errors (`PreconditionError`, `SystemctlError`,
  `PartitionInvalidError`, `HostUnsupportedError`, `JournalError`) → their message as now,
  plus hint;
- `OSError` → `vfio-isolate: <current> failed: <strerror>[: <filename>]` + hint;
- any other `Exception` → `vfio-isolate: <current> failed: <type>: <msg>` +
  `use -d for a traceback` + hint; with `-d` re-raise instead.

The hint depends on state: with `-u` and at least one record appended this run →
`run "vfio-isolate restore <file>" to undo`; without `-u` and `changed` → `changes made
before the failure remain`; nothing changed → no hint. The journal is closed by the
existing `finally` in `run()` before `main` prints. Interrupted `restore`: the journal is
neither unlinked nor rewritten, so the hint is to run `restore` again.

The errno table is checked in the VM before it is frozen (tasks 3.4): a `move-tasks` out
of `/` must produce the kernel-thread summary and no warnings, and one `irq-affinity
mask` run records the errnos real IRQs return.

### Nodesets: list grammar only, masks parsed in Python under `M`
`nodeset.lark` drops `mask_form` and `MASK_ENTRY`; `./build_parser` regenerates
`nodeset_parser.py`. The mask form dates from the 2020 parser for kernel mask files
(`123b93d`); nothing reads mask files now, and under `C` it shadowed 8-digit decimal lists.
Masks stay available as CLI input under their own prefix: `CPUNodeSet.from_mask(str)`
matches `[0-9a-f]{1,8}(,[0-9a-f]{1,8})*` (case-insensitive) and treats each group as a
32-bit word, most significant first; a mismatch raises `NodeSetSyntaxError`.
- Alternative: keep both forms in the grammar with separate start symbols. Rejected: the
  mask form is a few lines of Python, and two parsers from one standalone file need
  generator flags for no gain.

`NodeSetParser.parse` wraps lark exceptions in `NodeSetSyntaxError(ValueError)`; the
`range` transformer raises it for `a > b`. The click callbacks (`cb_cpu_nodeset`,
`cb_numa_nodeset`) turn `NodeSetSyntaxError`, empty results and `is_valid()` failures
into `click.BadParameter`, naming the missing CPUs/nodes. Empty-string construction
(`NodeSet("")`, used for empty kernel files) stays valid; only CLI input rejects empty.

### Complement universe per class
`NodeSet.negation()` uses `self.universe()`; `CPUNodeSet.universe()` is `possible_cpus()`,
`NUMANodeSet.universe()` is `possible_nodes()`.

### Governor validation in the click command
`cpu_governor` checks every CPU before queuing: missing `cpufreq/` or unreadable
`scaling_available_governors` → missing; governor not listed → unsupported. Any problem
raises `click.BadParameter` listing the CPUs (list form) and the union of governors
available on the selected CPUs. With `chain=True`, all callbacks run before `run()`, so no
action of the run executes.

## Risks / Trade-offs

- [`EIO` covers more than managed IRQs (chips without affinity support)] → the summary
  says "kernel-managed or not movable".
- [Root check rejects non-root users with capabilities] → accepted; no such use is known
  and the tool writes `/proc/sys/vm` and IRQ affinity, which need root anyway.
- [Breaking: `C<8 hex>` masks stop working] → they fail loudly: hex letters and leading
  zeros are syntax errors, large numbers are nonexistent CPUs; the same value works with
  `M`. The form was undocumented.
- [The failure collector is module state] → reset at the start of `main()`; tests call
  `main()`.

## Migration Plan

Ships in 0.6 together with the other breaking changes; the changelog note in readme-and-tests
documents `M`. Rollback: users stay on 0.5.2.
