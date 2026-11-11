## Context

See proposal.md. README (261 lines) mixes reference and recipes, uses `# vfio-isolate`
prompt lines, and has the broken examples listed there. Help strings live in the click
decorators in `cli.py`. The unit tests already have a `fake_host` fixture that builds a
sysfs/cgroup tree; its default size (8 CPUs, 1 node) is smaller than the README examples
(`C0-6,16-22`, `C8-15,24-31`: 32 CPUs).

## Goals / Non-Goals

**Goals:** the documentation spec; a test that would have caught the hook bug.

**Non-Goals:** man page; generated reference docs; executing README examples (the VM
suite covers execution); changing CLI behavior.

## Decisions

### README structure
1. Intro, the AMD X3D note moved below the intro.
2. Requirements and install (root, cgroup v2 with cpuset, Python ≥ 3.9, systemd optional),
   v1 users → 0.5.2, link to CHANGELOG.
3. Concepts: CPU/NUMA arguments (`C`, `N`, `M` with examples), chaining (`chain=True`,
   all arguments validated before anything runs), undo journal (`-u`, append, newest-first
   restore, failed steps kept), error reporting and exit statuses.
4. Command reference: one `###` section per command with synopsis, options, behavior,
   undo behavior.
5. Recipes: non-NUMA host with systemd (the existing example, fixed), experimental
   partition, libvirt hook.
6. Testing (unit + VM, VM run now ~10 s).
Command synopses are written by hand, not pasted `--help` output, so the README does not
need regenerating for every wording change; the coverage test keeps the list complete.

### Example conventions
Shell blocks are fenced as `sh`, commands without prompts, comments as `#` lines on their
own. Undo files: `/run/vfio-isolate.undo` in short examples; the hook sets `VM=win10` and uses
`UNDOFILE=/run/libvirt/qemu/vfio-isolate-$VM.undo` (libvirt's runtime dir, root only, gone
on reboot — right, since cpuset state does not survive a reboot either) and
`[ "$1" = "$VM" ] || exit 0`. If the `vfio-isolate` call in `prepare` fails, the hook
runs `restore` and exits non-zero, so libvirt aborts the VM start (the user's choice:
a VM without isolation should not start silently). `release` only restores when the undo
file exists, since a failed start may already have restored it, and libvirt may run
`release` after a failed `prepare`. `cpu-governor performance C$MCPUS`; kthreadd reset uses
`$(cat /sys/devices/system/cpu/possible)`. `M`/`N` examples written as invocations must fit
the fake host (32 CPUs, one node): e.g. `Mff00`, not `Mff,0000000f` (that one may appear in
prose). The pasted `--help` block at the top of the README is dropped (it drifts); the
README points to `vfio-isolate --help`.

Examples that parse can still be refused at run time (preconditions). The
`cpuset-create`/`cpuset-delete` examples (today `/test.slice`) are run once in the VM
before they go into the README; if a `.slice` name not known to systemd is refused, the
examples use a non-unit name.

### README example test
`tests/test_readme.py` parses README.md: fenced blocks tagged `sh`; per block, collect
`NAME=value` assignments, join `\` continuations, find commands starting with
`vfio-isolate` (also after `sudo `), substitute `$NAME`/`${NAME}`, split with `shlex`; any `$` left after substitution fails
the test (no silent half-substituted argv).
Each invocation runs `cli.main(argv)` on a fake host with 32 CPUs and governors
`performance powersave`, with `Executor.run` patched to return 0, so parsing, nodeset and
governor validation run but nothing executes. `restore <file>` reads the journal at parse
time, so the test rewrites restore paths (and `-u` paths) into `tmp_path` and creates an
empty valid journal there; nothing is created under the real `/run`. A lint test fails on `\` followed by
whitespace and on prompt prefixes in `sh` blocks; a prompt is `#` or `$` followed by
optional space and `vfio-isolate` or `sudo` (comment lines and the shebang are fine). A coverage test compares `cli.commands`
with the README's `###` command headings.
- Alternative: doctest-style execution against the fake host. Rejected: examples touch
  `/system.slice` and systemd; the fake would need the whole systemd setup for little gain
  over parse validation.

### Help texts
Short, factual; the group docstring carries chaining, root and exit statuses; nodeset
help via one shared string constant so all CPU arguments say the same. The
cpuset-commands spec's "no cgroup v1 references" requirement still holds.

### CHANGELOG 0.6.0 content
Derived from the archived proposals' **BREAKING** items and specs, not from memory:
cgroup v1 backend removed (stay on 0.5.2) and v1-only options (`--cpu-exclusive`,
`--mem-exclusive`, `--mem-migrate`, `--sched-load-balance`) removed; cpuset commands fail
clearly on hosts without a v2 cpuset hierarchy; undo file is a JSON Lines journal, 0.5.x
files refused (finish them with 0.5.2); `-u` appends to an existing journal; `restore`
deletes the journal on success and keeps failed steps otherwise; hex masks under `C`
replaced by `M`; bare/empty sets and reversed ranges are usage errors; root required;
errors exit 1 with one line instead of a traceback. New: systemd units via
`set-property`, experimental partitions, per-item failure summaries, governor validation.

### Review
The reviewer checks every behavioral sentence in the README and CHANGELOG against
`openspec/specs` (the tests only check invocations). The managed-IRQ `EIO` case is not
described as verified.

## Risks / Trade-offs

- [The README parser test is heuristic (only `sh` blocks, simple variable substitution)]
  → the convention is documented at the top of the test; blocks that are not shell (XML)
  are fenced with their own language and skipped.
- [Fake host with 32 CPUs] → a parameter of the fixture, defaults unchanged for other
  tests.
