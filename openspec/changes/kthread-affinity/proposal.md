## Why

Kernel threads stay in the root cgroup, so cpusets and `move-tasks` cannot keep them off
the VM's CPUs (#6). The README hook works around it with `taskset -pc $HCPUS 2` (pin
kthreadd, whose affinity new kernel threads inherit) and resets it to all CPUs on release.
That has no undo and leaves already running kernel threads (`kswapd`, `khugepaged`,
`kcompactd`, …) where they are.

## What Changes

- New command `kthread-affinity {mask|add} <cpus>`, shaped like `irq-affinity`: changes the
  affinity of kthreadd and of every kernel thread that accepts it. Per-CPU kernel threads
  (PF_NO_SETAFFINITY) are skipped. Undo restores each thread's previous
  affinity.
- Refused while CPUs are in isolated cpuset partitions: the kernel then restricts kthreadd
  itself (VM probe), and undo ordering would leave the wrong affinity behind.
- README: the hook recipe uses the command instead of `taskset`.

## Capabilities

### New Capabilities
- `kthread-affinity`: keeping kernel threads off the VM's CPUs with undo.

## Impact

- Code: new `vfio_isolate/kthread.py`, `action/kthread_affinity.py`, `cli.py`.
- Tests: fake kernel threads in `tests/conftest.py`, unit tests, a VM test, dry-run
  `describe`/`touches`, agreement cases.
