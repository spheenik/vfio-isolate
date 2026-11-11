## Why

The README and `--help` lag behind 0.6. Several copy-paste examples are broken: the libvirt
hook calls `cpu-governor performance` without CPUs (usage error, isolation never happens),
two blocks have a space after a trailing `\`, and prompt-style `# vfio-isolate` lines turn
into comments when pasted. Whole features are undocumented: `M`/`N` nodesets,
`move-tasks`, `irq-affinity add`, the root requirement, exit codes, per-item failure
reporting. Undo files are still suggested under `/tmp`. Nothing records the breaking changes
users meet when upgrading from 0.5.x. Nothing stops this drift from coming back.

## What Changes

- README rewritten around 0.6: requirements (root, cgroup v2, systemd optional), the
  nodeset forms `C`/`N`/`M`, chaining and the undo journal, error reporting and exit
  codes, one section per command (all options), then recipes (non-NUMA host, systemd
  hosts, experimental partition, libvirt hook), then testing.
- Examples fixed: no prompt prefixes, no broken line continuations, undo files under
  `/run`, the hook filters on the VM name, sets the governor only on the VM CPUs
  (`C$MCPUS`), and stops hardcoding `0-31` for kthreadd.
- `CHANGELOG.md` (new) with 0.6.0: **BREAKING** cgroup v1 dropped, hex masks under `C`
  replaced by `M`, JSON undo journal (0.5.x pickle files refused), root required; plus
  the new behavior. The README links it.
- `--help` texts complete: group description (chaining, root, exit codes), the
  `C`/`N`/`M` forms on every CPU/NUMA argument, `-u` append semantics, `restore` behavior,
  argument help for `irq-affinity`, `move-tasks`, `cpu-governor`.
- A test runs every `vfio-isolate` invocation in the README through the CLI against a fake
  host (parse and argument validation, no execution) and lints README shell blocks for
  broken continuations.
- CLAUDE.md trimmed and corrected (the "no pickle anywhere" claim ignores the generated
  parser).

## Capabilities

### New Capabilities
- `documentation`: README and `--help` cover every command, option and nodeset form;
  README examples are valid invocations and are checked by the test suite; breaking
  changes are recorded in `CHANGELOG.md`.

### Modified Capabilities
(none)

## Impact

- Files: `README.md`, `CHANGELOG.md` (new), `vfio_isolate/cli.py` (help strings only),
  `tests/test_readme.py` (new), `tests/conftest.py` (fake host sized for README examples
  if needed), `CLAUDE.md`.
- No behavior change of the CLI beyond help output.
