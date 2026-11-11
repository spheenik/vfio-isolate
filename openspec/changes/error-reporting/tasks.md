## 1. Nodeset input

- [x] 1.1 Drop `mask_form`/`MASK_ENTRY` from `nodeset.lark`, regenerate `nodeset_parser.py` with `./build_parser` (check lark is installed; the regenerated diff must be limited to the grammar change, not a different lark version's whole file)
- [x] 1.2 `NodeSetSyntaxError(ValueError)`: wrap lark errors in `NodeSetParser.parse`; reversed ranges raise it
- [x] 1.3 `CPUNodeSet.from_mask()` (1-8 hex digit groups, most significant first, case-insensitive)
- [x] 1.4 `universe()` per class; `negation()` uses it (fixes NUMA complement)
- [x] 1.5 `cb_cpu_nodeset`/`cb_numa_nodeset`: `C`/`N`/`M` forms; syntax errors, empty sets and nonexistent CPUs/nodes are `BadParameter` naming the bad items
- [x] 1.6 Tests: `M3c`, `Mff,0000000f`, `MFF`, `C10000000`, `C000000ff`, `C7-0`, `C`, `M`, `M0`, `Mxyz`, `C0-3,,5`, NUMA complement

## 2. cpu-governor validation

- [x] 2.1 Validate cpufreq presence and available governors for every CPU in the `cpu-governor` click command
- [x] 2.2 Tests: unknown governor (nothing executed in a chained run), missing cpufreq

## 3. Per-item failures

- [x] 3.1 Failure collector in `output.py` (errno table, immediate warnings for unexpected errnos, summary, `-v` lists); reset in `main()`, summary printed in a `finally`
- [x] 3.2 Report from `IRQ.set_affinity` and `CPUSet.add_pid`
- [x] 3.3 Tests: managed IRQs (EIO) summary and exit 0, `-v` listing, unexpected errno warning, repeated unexpected errno (one warning + count), kernel threads (EINVAL), restore path
- [x] 3.4 VM test: `move-tasks` out of `/` gives the kernel-thread summary and no `warning:` lines; run `irq-affinity mask` once in the VM and record the errnos seen; adjust the table if they differ
- [x] 3.5 Exit 1 when one irq-affinity/move-tasks execution changed nothing and had an unexpected errno (collector counts successes, per-execution scope); tests incl. expected-only total failure → 0

## 4. Stopping failures and root check

- [x] 4.1 `privileges.require_root()` called first in `Executor.run` and in the `restore` callback; `fake_host` patches it
- [x] 4.2 `Executor` tracks `current`, `changed`, records appended
- [x] 4.3 `main()`: OSError / known errors / other exceptions / KeyboardInterrupt and `Abort` formatting, restore hint rules, `-d` re-raise, exit 130
- [x] 4.4 Tests: non-root refused before any write, `--help` unprivileged, OSError with and without `-u`, unexpected exception with and without `-d`, interrupt during execution (exit 130, journal intact) and during parsing (exit 130, nothing changed)

## 5. Wrap-up

- [x] 5.1 Full default suite passes; VM suite passes (`scripts/vm-test`)
- [x] 5.2 CLAUDE.md: note the `C`/`N`/`M` forms, failure collector, `require_root` seam
