## 1. Executor and framework

- [x] 1.1 Global `-n/--dry-run` option; Executor dry mode (no root check, lock, journal, execute); `would record undo in` line; exit status per design
- [x] 1.2 Dry-run context (cpuset overlay) passed to `can_execute`/`describe`; real path passes None
- [x] 1.3 Audit `can_execute`/`record_undo`/`describe` of every action for writes

## 2. describe per action

- [x] 2.1 `describe` for every action in `ACTIONS` (current -> new values, unknown on permission errors, overlay-aware for cpusets)
- [x] 2.2 Coverage test: every action overrides `describe`; CLAUDE.md "new command" line mentions `describe`

## 3. restore -n and tests

- [x] 3.1 `restore -n`: validate, print steps newest record first, change nothing
- [x] 3.2 Read-only test: every README invocation with `-n` on the fake host leaves the tree unchanged, no journal, no lock, only read-only systemctl verbs
- [x] 3.3 Unit tests for every scenario; VM test: `-n` run as non-root inside the guest if feasible, else as root with a snapshot comparison
- [x] 3.4 README section "Dry run", CHANGELOG; full default suite and VM suite pass
