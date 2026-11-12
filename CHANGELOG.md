# Changelog

## 0.6.0 (unreleased)

### Breaking changes

- **cgroup v1 is no longer supported.** vfio-isolate needs the cgroup v2 unified hierarchy with the `cpuset`
  controller. Stay on 0.5.2 if your host uses cgroup v1 or a hybrid layout (`pip install vfio-isolate==0.5.2`).
  Commands that touch cpusets now fail with a clear error on hosts without a v2 cpuset hierarchy instead of acting on
  the wrong hierarchy.
- **The v1-only options of `cpuset-create` and `cpuset-modify` are removed:** `--cpu-exclusive`, `--mem-exclusive`,
  `--mem-migrate`, `--sched-load-balance`, their `--no-` forms and the short forms (`-ce`, `-nce`, `-me`, `-nme`,
  `-mm`, `-nmm`, `-lb`, `-nlb`). On v2 they were accepted and silently ignored; remove them from your scripts, they are
  now usage errors. For exclusive CPUs use the experimental `--partition` option.
- **Hex masks under `C` are replaced by `M`.** `C` is always a decimal CPU list now; `C000000ff` is a usage error.
  Write the mask with the `M` prefix instead, e.g. `M3c` or `Mff,0000000f`.
- **Bare or empty sets and reversed ranges are usage errors** (exit status 2): `C`, `N`, `C7-0`.
- **The undo file is a JSON Lines journal.** Undo files written by 0.5.x (pickle) are refused by `restore` and `-u`.
  Finish any VM prepared with 0.5.x first: install 0.5.2 (`pip install vfio-isolate==0.5.2`), run
  `vfio-isolate restore <file>`, then upgrade.
- **`-u` appends to an existing journal** instead of replacing the file; `restore` then undoes every recorded run,
  newest first. Existing files that are not journals, symlinks, files owned by someone else and files writable by group
  or others are refused. Use a fresh path (for example under `/run`) if you do not want runs to accumulate.
- **`restore` deletes the journal on success** and, if steps fail, rewrites it with only the failed steps and exits
  with status 1. Scripts that kept the file after a restore must not rely on it any more.
- **Root is required.** Any run that queues a command, and `restore`, exits with status 1 and
  `vfio-isolate: must be run as root` for other users. Run it with `sudo`; `--help` still works unprivileged.
- **Usage errors exit with status 2** (they were status 1 in 0.5.2, which crashed with a traceback on every error).
- **`restore` combined with `-u` is a usage error.**
- **`cpu-governor` validates the governor** against every selected CPU before anything runs; an unknown governor or a
  CPU without `cpufreq` is now a usage error (exit status 2) and nothing is executed. The kernel loads a governor
  module on demand when its name is written to `scaling_governor`, but `scaling_available_governors` lists only loaded
  governors; such a governor is now refused. Load it first (`modprobe cpufreq_<name>`).

### New

- `-n`/`--dry-run` previews a chain without changing anything: it checks the preconditions of each command in order
  and prints what each would do, with current and new values (`would set governor of CPUs 8-15: schedutil ->
  performance`). It takes no lock, writes no journal and does not need root where the files are readable;
  `restore -n FILE` (or `-n restore FILE`) previews an undo file. Values an earlier step of the chain changes are marked `(after earlier steps)`, and preconditions that depend on them are reported as checked only in a real run. What only a real run shows (hugepage shortfalls, IRQs the kernel refuses,
  unmovable tasks, a partition the kernel rejects) is not predicted.
- `workqueue-affinity mask|add CPUS` restricts the unbound kernel workqueues (kworkers) to other CPUs; CPUs in
  isolated partitions are never written; undo restores the previous mask.
- `kthread-affinity mask|add CPUS` keeps kernel threads off the VM's CPUs (#6): it changes the affinity of `kthreadd`
  (which new kernel threads inherit) and of every kernel thread that accepts it; per-CPU threads are skipped; undo restores each thread's previous affinity. Refused while CPUs are in isolated cpuset partitions. The
  libvirt hook recipe uses it instead of `taskset -pc ... 2`, which had no undo.
- `irq-affinity` also restricts `/proc/irq/default_smp_affinity`, so IRQs created later (QEMU's VFIO IRQs, requested
  after the libvirt `prepare` hook) start off the VM's CPUs. Undo is relative (gives back only the CPUs this run
  removed); a `mask` that leaves no online CPU in the default is refused. IRQs created while the VM runs are not
  journaled and keep the restricted affinity after `restore`.
- `irq-affinity` warns once per command when `irqbalance` is running, since it overwrites IRQ affinities.
- `hugepages [--node N<n>] PAGESIZE AMOUNT` adds pages to the hugepage pool (#2, #10); undo releases them again. If
  the kernel provides fewer pages than asked, the command fails, releases what it got and leaves no undo record.
- Runs are serialized by a lock (`/run/vfio-isolate.lock`), so concurrent hooks do not interleave.
- cpusets of systemd units (`*.slice`, `*.scope`, `*.service`) are changed with `systemctl set-property --runtime`,
  so the setting survives `systemctl daemon-reload`. `cpuset-create` and `cpuset-delete` are refused for systemd units
  and `/`; `cpuset-modify` is refused for `/`.
- Cgroups not owned by systemd are written directly, after enabling the `cpuset` controller in their ancestors.
  Undo restores the configured values, including empty (inherit).
- Experimental `cpuset-modify --partition member|root|isolated` with read-back validation of the kernel's partition
  state.
- The nodeset forms `C` (decimal CPU list), `N` (NUMA nodes) and `M` (hex mask as in `smp_affinity`); a bare `M` or
  `M0` is rejected like the other empty sets.
- One-line error messages instead of tracebacks (`vfio-isolate: <command> failed: <reason>`); use `-d` for the
  traceback.
- The undo journal is written before each command runs, so a failed or interrupted run can be undone with `restore`.
- Per-item failure summaries for `irq-affinity` and `move-tasks` (kernel-managed IRQs, kernel threads, exited tasks),
  with `-v` listing the items; failures that stop a run name the command and the `restore` hint; exit status 130 on
  Ctrl-C.
- `cpuset-delete` refuses a cpuset that has child cgroups (delete the children first).
- README section "Choosing CPUs": how to read SMT, L3, hybrid and NUMA topology from sysfs and turn it into
  arguments (X3D and hybrid hardware are untested by this project).
- README rewritten with a section per command and checked examples; `--help` texts describe chaining, the root
  requirement, exit statuses and the argument forms.

### Fixed

- `cpuset-delete` no longer fails occasionally with EBUSY (#9): a briefly busy cpuset is retried for about 2 seconds,
  moving its tasks again, before failing with "still in use".
- Undo steps of an action are applied in the right order, which fixes undoing `cpuset-delete` and the IRQ affinities
  restored after `irq-affinity`.
- `restore` no longer stops at the first failing step; it attempts every step and reports each failure.
- Undo of `move-tasks` no longer moves back tasks that were already in the target cpuset.
- Undo of a cpuset change no longer turns "inherit from parent" into a fixed CPU list (it captured
  `cpuset.cpus.effective`).
