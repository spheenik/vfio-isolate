## 1. workqueue-affinity

- [x] 1.1 `vfio_isolate/workqueue.py`: read requested (fallback cpumask) and isolated masks, write mask; hex mask parse/format in kernel group format (reuse existing mask helpers if present)
- [x] 1.2 Action `WorkqueueAffinity` (mask/add, isolated CPUs excluded, empty refused, undo rule from design), registered in `ACTIONS`; click command shaped like `irq-affinity`
- [x] 1.3 Fake workqueue files in `tests/conftest.py`; unit tests for every scenario; error mapping EINVAL/EOVERFLOW
- [x] 1.4 VM test: mask restricts `kworker/u*` Cpus_allowed_list; restore; with an isolated partition the isolated CPUs are never written

## 2. irqbalance warning

- [x] 2.1 Parse-time check in the `irq-affinity` command, once per command; unit tests with psutil patched

## 3. Docs

- [x] 3.1 README `### workqueue-affinity`, irqbalance note in `### irq-affinity`, recipe line; CHANGELOG New entries
- [x] 3.2 Full default suite and VM suite pass
