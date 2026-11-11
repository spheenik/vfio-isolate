## Why

Failures are reported badly or not at all. IRQs and tasks that cannot be moved are
swallowed (`print_debug` only), so a run "succeeds" with the VM's CPUs still serving IRQs.
An `OSError` mid-run surfaces as a traceback with no hint that `restore` exists. Bad input
parses to something unintended: `C` also accepts an undocumented hex mask form, so
`C10000000` is CPU 28 instead of CPU 10000000; `C7-0` is an empty set, and a bare `C` is
accepted. A wrong governor name fails only after
earlier actions already changed the host. Running as a normal user fails halfway with
`EACCES`.

## What Changes

- Root check: a run that would change anything (any action or `restore`) is refused
  before the first change when the effective UID is not 0. `--help` and usage errors
  still work unprivileged.
- Per-item failures in `irq-affinity` and `move-tasks` (and their undo during `restore`):
  - expected ones (IRQ `EIO`: kernel-managed IRQ; task `EINVAL`: kernel thread; task
    `ESRCH`, IRQ `ENOENT`: gone) are counted and summarized in one line per kind on stderr;
    `-v` lists every item;
  - any other errno is a warning on its first occurrence, and repeats are counted;
  - the run continues and the exit status stays 0.
- Failures that stop a run: `vfio-isolate: <command> failed: <reason>` on stderr, exit 1.
  With `-u`, the message adds `run "vfio-isolate restore <file>" to undo`. Without `-u`,
  it says the changes made before the failure remain. Unexpected exceptions print one line
  plus `use -d for a traceback`; `-d` re-raises.
- Ctrl-C: reports the interrupted command (and the restore hint with `-u`), exit 130.
- Nodeset input:
  - **BREAKING** (undocumented form) `C` is always a decimal CPU list; the hex mask form
    hidden in it (`C000000ff`) is removed. Hex masks move to a new prefix `M`
    (`M3c`, `Mff,0000000f`: comma-separated groups of 1-8 hex digits, most significant
    first, as in `/proc/irq/*/smp_affinity`). Documented in readme-and-tests.
  - Syntax errors, reversed ranges (`C7-0`) and empty sets (`C`, `N`) are usage errors.
- `cpu-governor` checks, at parse time and for every CPU, that `cpufreq/` exists and that
  the governor is in `scaling_available_governors`; otherwise it is a usage error that
  names the CPUs and the available governors.
- Bug fix: `NUMANodeSet.negation()` uses the possible NUMA nodes, not the possible CPUs.

## Capabilities

### New Capabilities
- `error-reporting`: root check, per-item failure summaries, run-stopping failure
  messages with restore hint, interrupt handling, exit codes.
- `nodeset-input`: the `C`/`N`/`M` argument forms, what they accept and what they reject.
- `cpu-governor`: governor validation before any change.

### Modified Capabilities
(none)

## Impact

- Code: `cli.py` (callbacks, `Executor.run`, `main`), `nodeset.py` + `nodeset.lark` +
  regenerated `nodeset_parser.py`, `irq.py`, `cpuset.py` (`add_pid`), `output.py`
  (failure collector), `action/irq_affinity.py`, `action/move_tasks.py`, `cpu.py`.
- Users who passed masks as `C<8 hex digits>` must switch to `M` or lists. The README never
  documented the mask form.
- Tests: new unit tests; existing tests run as non-root, so the root check needs a seam
  (`fake_host` patches it).
