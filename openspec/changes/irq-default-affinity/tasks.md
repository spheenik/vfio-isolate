## 1. Implementation

- [x] 1.1 Move the hex-mask formatter from `workqueue.py` to `nodeset.py`; `workqueue.py` uses it (no behavior change)
- [x] 1.2 `vfio_isolate/irq.py`: read/write `/proc/irq/default_smp_affinity` via `fsroot`, `exists` check
- [x] 1.3 Action `IRQDefaultAffinity` (`irq-default-affinity`): `can_execute` refusal, relative `record_undo`, `execute`, `describe`/`touches`/`reads`; registered in `ACTIONS`
- [x] 1.4 `cli.py`: `irq-affinity` queues the default step before the per-IRQ steps, outside their batch/group
- [x] 1.5 Fake host: `default_smp_affinity` (and online CPUs) in `tests/conftest.py`; unit tests for every scenario in `specs/irq-affinity/spec.md`; existing dry-run tests updated

## 2. VM test and docs

- [x] 2.1 VM test: mask sets the default, restore brings it back; masking all online CPUs is refused (check the kernel's own EINVAL too)
- [x] 2.2 README `### irq-affinity` bullet (default, relative undo, IRQs created while the VM runs) and dry-run example line
- [x] 2.3 CHANGELOG entry
- [x] 2.4 Full default suite and VM suite pass

## 3. Host acceptance (needs root on the host; ask first)

- [x] 3.1 Reinstall `/opt/vfio-isolate` with the VM off; hook-driven start: no `vfio-*` IRQ on CPUs 8-15,24-31; after shutdown the default is `ffffffff`
