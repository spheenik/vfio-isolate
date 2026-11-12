## Why

`irq-affinity` moves only the IRQs that exist when it runs. QEMU requests the VFIO IRQs of
passthrough devices after the libvirt `prepare` hook, and the guest driver enables more
vectors later; the kernel gives every new IRQ the affinity from
`/proc/irq/default_smp_affinity` (all CPUs by default). On a real host (2026-11-12) every
VFIO IRQ of a freshly started VM landed on the VM's CPUs, the least loaded ones, although
`irq-affinity mask` had run in `prepare`.

## What Changes

- `irq-affinity mask|add <cpus>` also applies the operation to
  `/proc/irq/default_smp_affinity`, before it changes the existing IRQs, so IRQs created
  later start with the same restriction.
- Undo is relative: it adds back only the CPUs this run removed (or removes only the CPUs
  it added), so overlapping VMs do not hand each other's CPUs back.
- A `mask` whose result has no online CPU is refused before any change (unlike existing
  IRQs, there is no "take all other CPUs" fallback for the default).
- Hosts without the file: the default is skipped silently.
- Dry run shows one extra line for the default.
- README: `### irq-affinity` and the dry-run example; note that IRQs created while the VM
  runs are not journaled (host IRQs created then keep the restricted affinity after restore).

## Capabilities

### New Capabilities

### Modified Capabilities
- `irq-affinity`: the command also restricts the default affinity for new IRQs, with
  relative undo and a refusal when no online CPU would remain.

## Impact

- `vfio_isolate/action/` (new internal action queued by `irq-affinity`, registered in
  `ACTIONS` for the journal; no new CLI command), `cli.py`, a shared hex-mask formatter
  (today in `workqueue.py`), tests, README, CHANGELOG.
- Journals written by older versions are unaffected; journals with the new record need
  this version to restore.
