## 1. Codec and action registry

- [ ] 1.1 Give every Action a stable `name` (CLI command name) and expose `ACTIONS = {name: cls}` in `action/__init__.py`
- [ ] 1.2 Add the JSON codec `encode(execution) -> dict` / `decode(dict) -> Execution` driven by Param field types (nodesets ↔ list-form string, IRQ/CPU ↔ int, Enum ↔ member name, str/int/bool/None pass-through, any field may be None); raise `JournalError` on unknown action/field/missing field/type. Keep `Executor.add`'s kwargs→Param path separate from it
- [ ] 1.3 Tests: round-trip every action's Param through encode/decode (incl. None fields); unknown action, unknown field, missing field rejected

## 2. Journal file

- [ ] 2.1 New module `vfio_isolate/journal.py`: `open_for_append(path)` (O_RDWR|O_CREAT|O_APPEND|O_NOFOLLOW|O_CLOEXEC 0600, fstat regular/owner==euid/no g+w,o+w, header written if empty else validated) with `append(steps)` doing flush + fsync; `read_journal(path) -> list[list[Execution]]` (O_NOFOLLOW, same fstat checks, header/version, 0.5.x pickle detection by first bytes, truncated-last-line dropped with warning, corrupt line elsewhere rejected, every step decoded up front); `rewrite(path, records)` via same-dir temp file + os.replace
- [ ] 2.2 Tests: header written; mode 0600; append to existing valid journal; non-journal existing file rejected untouched; symlink and dangling symlink rejected; mode 0666 rejected; pickle bytes (`\x80`, `(`, `]`) give the 0.5.x message; wrong version rejected; truncated last line dropped; corrupt middle line rejected; unknown action rejects whole file

## 3. Executor and actions

- [ ] 3.1 `can_execute` preconditions: CPUSetCreate (target must not exist), CPUSetModify/CPUSetDelete/MoveTasks (named cpusets must exist); failure raises `PreconditionError`
- [ ] 3.2 Tolerances in execute: `CPUSetCreate` succeeds if the cpuset exists; `CPUSetDelete` succeeds if it is already gone
- [ ] 3.3 Executor: open the journal up front when `-u` is set (before any action); per action `can_execute` → materialize `record_undo` → append non-empty record + fsync → `execute`; drop the reversed pickle dump; no `pickle` import left in the package
- [ ] 3.4 `restore`: click callback reads/validates/decodes the whole journal and queues a `RestoreBatch`; Executor's cgroup pre-check includes its steps; applies records newest-first with per-step try/except and stderr report; unlink on success, else rewrite with failed records only and exit 1; missing file → error exit 1; `-u` together with `restore` → usage error
- [ ] 3.5 `main()` maps `JournalError` and `PreconditionError` (and restore partial failure) to stderr + exit 1

## 4. Spec scenario tests

- [ ] 4.1 Move the os.mkdir/os.rmdir patching for cgroup dirs into the `fake_host` fixture (opt-in helper) so cpuset-create/delete run end-to-end; add cpufreq governor files and IRQ smp_affinity_list files to the fake tree as needed
- [ ] 4.2 `tests/test_undo.py`: every scenario in `specs/undo-journal/spec.md`. Order and append scenarios use `cpu-governor` (state read and written in the same file), NOT cpuset-modify (the fake tree never updates `cpuset.cpus.effective`). For the newest-first, cpuset-delete, IRQ-mask, prepare-twice and restore-residue scenarios, verify the test fails when the behaviour is broken (e.g. revert to global reversal / truncate instead of append) and say so in the report
- [ ] 4.3 Remove or adjust the old pickle-based undo tests in `tests/test_cli.py`; keep `test_restore_checked_before_executing` meaningful

## 5. Docs

- [ ] 5.1 README Undo section: journal behaviour (append on repeat runs, restore retries and deletes on success, 0.5.x files refused); don't change the suggested location yet
- [ ] 5.2 Update `CLAUDE.md` (journal module, action names/registry, no pickle)
- [ ] 5.3 `openspec validate undo-journal --strict` and full pytest pass
