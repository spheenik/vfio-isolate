## Why

Two sources of host noise on the VM's CPUs are not handled today:
- Unbound kernel workqueues (writeback, block I/O, crypto, …) run their kworkers on every
  CPU. VFIO tuning guides restrict them next to IRQ affinity. The kernel does this itself
  only for CPUs in isolated cpuset partitions.
- `irqbalance`, if running, rewrites IRQ affinities and silently undoes `irq-affinity`.

## What Changes

- New command `workqueue-affinity {mask|add} <cpus>`, shaped like `irq-affinity`: `mask`
  removes the CPUs from the global unbound workqueue cpumask, `add` adds them. Undo
  restores the previous requested mask.
- CPUs the kernel currently isolates (`cpumask_isolated`) are never written into the
  mask, by the command or by its undo (VM probe: a sysfs write overrides the isolation).
- `irq-affinity` warns once per command when an `irqbalance` process is running.
- README: `### workqueue-affinity` section, irqbalance note, recipe line.

## Capabilities

### New Capabilities
- `workqueue-affinity`: restricting unbound workqueues with undo.

### Modified Capabilities
- `irq-affinity` (new spec file for the warning; the command itself has no spec yet).

## Impact

- Code: new `vfio_isolate/workqueue.py`, `action/workqueue_affinity.py`, `cli.py`
  (command, irqbalance check).
- Tests: fake workqueue files in `tests/conftest.py`, unit tests, a VM test.
