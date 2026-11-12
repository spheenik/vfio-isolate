## Context

`irq-affinity` queues one `IRQAffinity` step per IRQ listed in `/proc/irq` at queue time
(one batch, one failure group; per-IRQ write errors are collected, never fatal).
`/proc/irq/default_smp_affinity` is a hex mask (comma-separated 32-bit groups); there is
no `_list` variant. `workqueue.py` already has `format_mask` for this format and
`CPUNodeSet.from_mask` parses it.

## Decisions

- **Separate internal action** `IRQDefaultAffinity` (name `irq-default-affinity`), queued
  by the `irq-affinity` command before the per-IRQ steps, outside their batch and failure
  group. Registered in `ACTIONS` so the journal can name it; no click command (the README
  heading test covers click commands only). Alternative rejected: a sentinel `IRQ` — it
  would leak into the journal's IRQ encoding, the failure collector and `touches`.
- **Param**: `operation: DefaultAffinityOperation` (`mask`, `add`) and `cpus`. Undo of
  `mask` is `add` of `old ∩ cpus`; undo of `add` is `mask` of `cpus − old`. Nothing is
  recorded when that set is empty. Relative, so concurrent VMs compose (same reasoning as
  the per-IRQ undo).
- **Refusal**: `can_execute` reads the default and the online CPUs
  (`/sys/devices/system/cpu/online`) and raises `PreconditionError` when a `mask` result
  has no online CPU. The undo `mask` (after an `add`) goes through the same check; it can
  only fail if someone else changed the default meanwhile, and then restore reports it as
  a failed step like any other.
- **Missing file**: `can_execute` passes, `record_undo` yields nothing, `execute` does
  nothing, `describe` returns no line.
- **Mask helpers**: move `format_mask` from `workqueue.py` to `nodeset.py` (as
  `CPUNodeSet.to_mask_form()` or a module function) and use it from both.
- **Dry run**: `describe` → `set default IRQ affinity: <old> -> <new>` (list forms);
  `touches` `{("irq-default",)}`; `reads` the same key so a second `irq-affinity` in one
  chain shows `(after earlier steps)`.

## Risks

- IRQs created while the VM runs are not journaled. Host IRQs created in that window
  (hotplug, driver reload) keep the restricted affinity after restore. VFIO IRQs disappear
  with QEMU. Documented in the README.
- Managed IRQs ignore the default (the kernel spreads them); no change there.
- With posted interrupts (AVIC/APICv + IOMMU), VFIO MSIs mostly bypass the host CPU; the
  change still decides where the host-side fallback and INTx handling run.
- Acceptance on a real host: after a hook-driven VM start, no `vfio-*` IRQ's
  `smp_affinity_list` contains a VM CPU; after shutdown the default is back to all CPUs.
  Unit and VM suites prove only write and restore.
