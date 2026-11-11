## Context

`/sys/devices/virtual/workqueue/` has `cpumask` (effective, writable), `cpumask_requested`
(last written value) and `cpumask_isolated` (CPUs in isolated partitions). Values are hex
masks in the kernel's comma-separated 32-bit-group format. VM probes on kernel 7.2:
- Writing `0f` restricts every `kworker/u*` thread to CPUs 0-3; per-workqueue masks
  (`writeback/cpumask`) keep their value, and the global mask still constrains them.
- Empty mask → EINVAL; a CPU beyond the possible CPUs → EOVERFLOW.
- With an isolated partition on 4-7: `cpumask=0f`, `requested=ff`, `isolated=f0`. A write
  of `30` makes `cpumask=30`, i.e. the write overrides the isolation.
- Per-CPU (bound) kworkers cannot be moved; only unbound workqueues are affected.

## Decisions

### Same shape as irq-affinity
`workqueue-affinity mask <cpus>` removes CPUs, `add <cpus>` adds them, so a hook passes the
same VM-CPU variable to both commands. The new mask is computed from `cpumask_requested`
(fallback `cpumask` on kernels without it). A result without an online CPU is refused before
writing: `no CPU would remain for unbound workqueues` (the mask is written as computed;
only the check looks at online CPUs).

### Refusal while CPUs are isolated
`mask`/`add` fail before writing when `cpumask_isolated` is non-empty (`CPUs <list> are in
isolated cpuset partitions; the kernel already keeps unbound workqueues off them. Run
workqueue-affinity before creating the partition, or leave it out`). Reason: a write drops the
isolated CPUs from `cpumask_requested`. If the partition was created earlier in the chain,
restore would undo the workqueue step while the partition is still active (writing old
requested minus isolated), and the partition undo would then recompute the effective mask
from the reduced requested mask: the isolated CPUs are gone from the workqueue mask until
reboot. Restore undoes the newest record first, so with the safe order (workqueue step, then
partition) the partition is removed before the workqueue mask is restored.

### Undo
Undo writes the previous requested mask minus the CPUs isolated at undo time. If that has no
online CPU, it writes the online CPUs that are not isolated. This only matters when a
partition was created after the workqueue step (it is then undone first, so normally nothing
is isolated at that point); the rare residue loses the isolated CPUs from `requested` if the
partition is removed later, which beats putting workqueues onto isolated CPUs.

### Errors
EOVERFLOW → `CPUs beyond the highest possible CPU`; EINVAL → `the kernel rejected mask <m>`.
Both stop the run like other precondition errors.

### irqbalance
`irq-affinity` checks (psutil, by process name `irqbalance`) at parse time and prints once:
`vfio-isolate: warning: irqbalance is running and will overwrite IRQ affinities; stop it or ban the VM's
CPUs in its configuration (IRQBALANCE_BANNED_CPULIST)`. No automatic stop: that is a
service-management decision the user should make.

## Risks

- Whether restricting unbound workqueues measurably helps a gaming VM is untested; the
  user plans host measurements.
- The isolation override on write looks like a kernel quirk; it may change in later
  kernels. The refusal is safe either way.
