## 1. Test harness first

- [x] 1.1 `fake_host` option for CPU count (default unchanged); README test helper that extracts `sh` blocks, assignments, continuations and `vfio-isolate` invocations
- [x] 1.2 Tests: invocation parse test (Executor.run patched, `$` leftovers fail, `-u`/restore paths rewritten into tmp_path), lint test (continuations, prompts), command coverage test — marked `xfail(strict=True)` until 3.3, since the current README fails them

## 2. Help texts

- [x] 2.1 Group docstring (chaining, root, exit statuses), shared nodeset help string on all CPU/NUMA arguments, `-u`, `restore`, `irq-affinity`, `move-tasks`, `cpu-governor` argument help
- [x] 2.2 Test: `cpuset-modify --help` mentions C, N, M; no cgroup v1 text (existing test)

## 3. README and CHANGELOG

- [x] 3.0 Run the README's cpuset-create/cpuset-delete examples once in the VM (`scripts/vm-test` with a small temporary test); choose example cgroup names accordingly
- [x] 3.1 Rewrite README per design structure; fix examples (hook name filter, abort VM start on failure (restore then exit non-zero; release guarded by file existence), `cpu-governor performance C$MCPUS`, kthreadd via possible CPUs, `/run` undo paths, no prompts, no broken continuations); fix typos
- [x] 3.2 `CHANGELOG.md` with 0.6.0 per design (derived from archived BREAKING items), linked from README
- [x] 3.3 Remove the xfail markers; README tests pass
- [x] 3.4 Review: every behavioral sentence in README/CHANGELOG checked against openspec/specs

## 4. Wrap-up

- [x] 4.1 CLAUDE.md trimmed (target ≤ 50 lines), pickle sentence corrected (generated parser), pointers to README/CHANGELOG conventions
- [x] 4.2 Full default suite and VM suite pass
