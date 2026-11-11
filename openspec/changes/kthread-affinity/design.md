## Context

VM probes on kernel 7.2 (8 CPUs):
- New kernel threads inherit kthreadd's (PID 2) affinity: after `taskset -pc 0-1 2`, a new
  `jbd2/loop0-8` thread had `Cpus_allowed_list: 0-1`.
- Of 103 children of kthreadd, 18 accepted `sched_setaffinity` (kswapd0, khugepaged,
  kcompactd0, ksmd, oom_reaper, kauditd, …); 85 refused (per-CPU threads,
  PF_NO_SETAFFINITY → EINVAL).
- Creating an isolated partition on CPUs 4-7 changed kthreadd's affinity from 0-7 to 0-3
  by itself.

## Decisions

### Which threads
Kernel threads are identified by the PF_KTHREAD flag (0x00200000) in field 9 of
`/proc/<pid>/stat`, not by parent PID, plus kthreadd itself. Threads with PF_NO_SETAFFINITY
(0x04000000, the per-CPU threads) always fail with EINVAL and are skipped, so normal runs
print no per-CPU summary, the journal holds only movable threads and dry-run counts are
right; kthreadd is never skipped. The list is taken when the
command line is parsed, like the IRQ list; threads created later inherit kthreadd's
affinity, which the command sets.

### Same shape as irq-affinity
`mask <cpus>` removes the CPUs from each thread's current affinity; if none would remain,
the thread gets all online CPUs except the masked ones; if that set is empty, the command is
refused ("no CPU would remain").
`add <cpus>` adds them. One execution per thread in one failure scope (like
`move-tasks`): EINVAL (a thread that became per-CPU meanwhile) and ESRCH (thread exited) are
expected and only counted in the summary; other errors are reported. kthreadd is handled first.

### Undo
Each thread's previous affinity is recorded together with its `starttime` (stat field 22)
and comm. Before restoring, /proc/<pid>/stat is re-read; the thread must still have
PF_KTHREAD and the same starttime (comm is only kept for messages: workers rename
themselves). On a mismatch or a missing entry (PID reuse, exit) nothing is touched and the
step counts as exited (expected). ESRCH on restore is success. The new Param fields are
required in the journal, so an incomplete step fails to decode cleanly. Restore does not
re-check isolation: with a different isolated partition active at release, kthreadd's
previous affinity is restored as recorded (accepted).

### Isolated partitions
Refused while `cpumask_isolated` is non-empty, with the same reasoning and message style
as `workqueue-affinity`: the kernel already restricts kthreadd then, and restoring an
affinity recorded while a partition was active, after the partition is gone, would keep
kernel threads off those CPUs.

### Dry run
`describe_many` summary: `set affinity of kthreadd and N of M kernel threads: ...`
(threads that refuse anyway cannot be known in advance; say so). Touches `("kthread", pid)`;
reads also `("isolation",)`; refusal follows the isolation tracking of `workqueue-affinity`.
