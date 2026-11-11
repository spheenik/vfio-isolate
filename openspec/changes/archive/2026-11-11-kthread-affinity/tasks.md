## 1. Command

- [x] 1.1 `vfio_isolate/kthread.py`: list kernel threads (PF_KTHREAD), read/set affinity (os.sched_getaffinity/setaffinity)
- [x] 1.2 Action `KThreadAffinity` (mask/add/restore, refusal while isolated, failure scope, describe/describe_many/touches/reads), registered in `ACTIONS`; click command
- [x] 1.3 Fake kernel threads in `tests/conftest.py`; unit tests for every scenario; dry-run and agreement cases
- [x] 1.4 VM test: mask moves kthreadd and movable threads, new kthread inherits, restore; refusal with an isolated partition

## 2. Docs

- [x] 2.1 README `### kthread-affinity`, hook recipe without `taskset`, CHANGELOG
- [x] 2.2 Full default suite and VM suite pass
