## 1. Journal and Executor

- [x] 1.1 `journal._Appender`: remember the offset before each append; `discard_last()` truncates to it and fsyncs
- [x] 1.2 `RolledBackError(PreconditionError)` in `action/action.py`; `Executor.run` catches it from `execute`, discards the record, fixes `records`/`changed`, re-raises
- [x] 1.3 Run lock: exclusive `flock` on `fsroot.path("/run/vfio-isolate.lock")` for all of `Executor.run`
- [x] 1.4 Unit tests: rolled-back action leaves only earlier records; first-change case says nothing changed; lock taken (second locker blocks)

## 2. hugepages command

- [x] 2.1 `vfio_isolate/hugepages.py`: pool paths, read/write count, sizes, size parsing/formatting
- [x] 2.2 Action `HugePages` (add / release, shortfall → write back, `RolledBackError`), registered in `ACTIONS`
- [x] 2.3 click command with parse-time validation (size, node, count), help text
- [x] 2.4 Fake pool in `tests/conftest.py` with a capacity model (writes clamp to capacity; lowering keeps an "in use" count)
- [x] 2.5 Unit tests for every scenario in `specs/hugepages/spec.md`

## 3. VM test and docs

- [x] 3.1 VM test: add 2M pages, restore; impossible count → exit 1, pool unchanged, journal without record; release with a mapped page in use
- [x] 3.2 README `### hugepages` section, hook recipe line, 2M versus 1G notes (VM results; 1G recommendation marked pending)
- [x] 3.3 CHANGELOG New entry; help test
- [x] 3.4 Full default suite and VM suite pass

## 4. After host tests (user at home)

- [x] 4.1 Host test: runtime 1G allocation after uptime; reboot with `hugetlb_cma=`, check dmesg and allocation
- [x] 4.2 README 1G recommendation from those results
