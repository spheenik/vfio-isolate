# vfio-isolate

vfio-isolate is a command line tool for Linux that facilitates CPU and memory isolation for running virtual machines
with guaranteed latency. It partitions CPUs between the host and a VM (cpusets), moves IRQs away from the VM's CPUs,
sets the CPU governor, drops caches and compacts memory, and can record how to undo all of it.

For the full option list of any command run `vfio-isolate --help` or `vfio-isolate <command> --help`.

## Requirements and installation

- Linux with cgroup v2 (the unified hierarchy) and the `cpuset` controller available. cgroup v1 is not supported
  since 1.0; v1 users stay on 0.5.2: `pip install vfio-isolate==0.5.2`.
- Python 3.9 or newer.
- Root. Every run that queues a command, and `restore`, is refused with `vfio-isolate: must be run as root` (exit
  status 1) for other users. `--help` and usage errors do not need root.
- systemd is optional. On systemd hosts, cpusets of systemd units are changed through systemd (see
  [cpuset-modify](#cpuset-modify)).

```sh
pip install vfio-isolate
```

Upgrading from 0.5.x: see [CHANGELOG.md](https://github.com/spheenik/vfio-isolate/blob/master/CHANGELOG.md) for the breaking changes.

## Concepts

### CPU and NUMA arguments

Arguments that take CPUs accept three forms:

- `C<list>`: decimal CPU numbers and ranges, e.g. `C0-3,8`. `C` is never read as a mask.
- `N<list>`: NUMA nodes, expanded to all CPUs of those nodes, e.g. `N0`.
- `M<mask>`: a hex CPU mask as in `/proc/irq/*/smp_affinity`: groups of 1 to 8 hex digits separated by commas, most
  significant group first, each group 32 bits, case-insensitive. `M3c` is CPUs 2-5; `Mff,0000000f` is CPUs 0-3 and
  32-39.

Arguments that take NUMA memory nodes (`--mems`) accept only `N<list>`, e.g. `N0` or `N0-1`.

```sh
vfio-isolate irq-affinity mask C2-5,8-11
vfio-isolate irq-affinity mask N0
vfio-isolate irq-affinity mask Mff00
```

Syntax errors, reversed ranges (`C7-0`), ranges ending above 65535, empty sets (`C`, `N`, `M`, `M0`), and CPUs or NUMA
nodes that do not exist (including `N` nodes without CPUs given as a CPU argument) are usage errors (exit status 2).
They are reported before anything is changed.

### Choosing CPUs

vfio-isolate does not pick CPUs for you. A common split:

- Give the VM whole physical cores (both SMT threads of each), ideally a whole L3 cache domain (a CCD or CCX on AMD).
- Keep CPU 0 and its SMT sibling for the host.
- On NUMA hosts keep the VM's CPUs and its memory on one node.

Read the topology from sysfs:

```sh
# SMT siblings (one line per CPU)
grep . /sys/devices/system/cpu/cpu*/topology/thread_siblings_list

# L3 cache domains: CPUs sharing an L3, and its size (index3 is usually L3, so check `level`)
for c in /sys/devices/system/cpu/cpu[0-9]*/cache/index*; do
    [ "$(cat $c/level)" = 3 ] && echo "$(cat $c/shared_cpu_list) $(cat $c/size)"
done | sort -u

# Intel hybrid CPUs only (these files do not exist elsewhere)
cat /sys/devices/cpu_core/cpus /sys/devices/cpu_atom/cpus

# NUMA nodes
grep . /sys/devices/system/node/node*/cpulist
```

`lscpu -e` and `lstopo` (from hwloc) show the same information.

On AMD X3D CPUs with two CCDs, the CCD with the larger L3 is the V-cache CCD. Which side should get it depends on the
workload; giving it to the VM is a common choice for games. On Intel hybrid CPUs, giving the P-cores to the VM is the
common choice. This project has not tested X3D or hybrid hardware; treat both as reports from users, not as
recommendations.

Example: a 16-core/32-thread CPU with two CCDs, CPUs 0-7,16-23 on CCD0 and 8-15,24-31 on CCD1. The host keeps CCD0
(`C0-7,16-23`), the VM gets CCD1 (`C8-15,24-31`):

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo \
    cpuset-modify --cpus C0-7,16-23 /system.slice \
    cpuset-modify --cpus C0-7,16-23 /user.slice \
    irq-affinity mask C8-15,24-31 \
    workqueue-affinity mask C8-15,24-31 \
    kthread-affinity mask C8-15,24-31
```

### Chaining

Commands can be chained in one invocation. They run in the order given, and all arguments are validated before the
first command runs.

```sh
sudo vfio-isolate \
    drop-caches \
    cpu-governor performance C8-15,24-31 \
    compact-memory
```

`cpu-governor` additionally checks, while arguments are parsed, that every selected CPU has a `cpufreq` directory and
offers the governor; otherwise the whole run is a usage error and nothing is executed. The kernel loads a governor
module on demand when its name is written to `scaling_governor`, but `scaling_available_governors` lists only loaded
governors, so such a governor is refused: load it first (`modprobe cpufreq_<name>`).

### Undo journal

With `-u <file>` vfio-isolate records how to undo each command in a journal file (plain text, JSON Lines).

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo cpuset-create --cpus C1-4 /vfio-test
sudo vfio-isolate restore /run/vfio-isolate.undo
```

- The undo steps of each command are appended to the file and made durable before that command changes anything, so
  the journal is complete even if a run fails half way. Commands that never started record nothing.
- If the file already exists and is a journal, later runs with `-u` append to it. `restore` then undoes every
  recorded run, newest first, back to the state before the first one.
- `restore` continues past steps that fail and reports them on stderr. If everything succeeded the file is deleted;
  otherwise it is rewritten to contain only the failed steps, and the exit status is 1, so you can fix the problem and
  run `restore` again.
- The file is created with mode 0600. Symlinks, files not owned by the current user and files writable by group or
  others are refused for both `-u` and `restore`, as is an existing `-u` file that is not a journal. These checks
  happen before any command of the chain makes a change. `-u` and `restore` cannot be used in the same command.
- The journal only describes known commands and their parameters; restoring it does not execute arbitrary code.
- Undo files written by vfio-isolate 0.5.x are not supported and are refused. Run `restore` with 0.5.2
  (`pip install vfio-isolate==0.5.2`) for any VM prepared with 0.5.x before upgrading.
- Keep the undo file on a volatile path such as `/run`: cpuset state does not survive a reboot either.

### Dry run

`-n` (`--dry-run`) checks a chain and prints what it would do, without changing anything: no write under `/sys`,
`/proc` or the cgroup tree, no state-changing `systemctl` call, no journal and no lock. Use it to try a hook line
before the first real run.

```sh
vfio-isolate -n -u /run/vfio-isolate.undo \
    cpuset-modify --cpus C0-7,16-23 /system.slice \
    irq-affinity mask C8-15 \
    workqueue-affinity mask C8-15 \
    hugepages 2M 16G \
    cpu-governor performance C8-15
```

```
would record undo in /run/vfio-isolate.undo
would set unit system.slice (systemd): AllowedCPUs 0-31 -> 0-7,16-23
would set default IRQ affinity: 0-31 -> 0-7,16-31
would change affinity of 41 of 57 IRQs (mask 8-15)
would set unbound workqueue mask: 0-31 -> 0-7,16-31
would add 16G in 2M pages (8192) to the pool, now 0; whether the kernel can supply them shows only in a real run
would set governor of CPUs 8-15: schedutil -> performance
```

- Preconditions are checked in order, as in a real run. The first one that fails ends the preview with
  `vfio-isolate: dry run: <command> failed: <reason>` and exit status 1.
- The preview follows the chain: a cpuset created by an earlier step exists for the later ones (`set cpuset /a (new):
  cpus 8-15`), and task counts that depend on earlier steps are marked `(after earlier steps)`. Other values an
  earlier step changes (a cpuset's CPUs, a governor, an IRQ's affinity, the workqueue mask, a kernel thread's affinity,
  the hugepage pool) are not
  simulated: the later step shows `(after earlier steps)` instead of the current value, and a precondition that
  depends on them is not evaluated; the preview says `(precondition checked only in a real run: depends on earlier
  steps)`.
- The CPUs that earlier steps put into isolated cpuset partitions are tracked where they are known exactly (a
  `cpuset-modify --cpus ... --partition isolated` on a cpuset that is not a partition yet, including one created
  earlier in the chain). A later `workqueue-affinity` or `kthread-affinity` `mask`/`add` then refuses exactly like a real run (exit status 1).
  Where the isolation is not exactly known (a partition without `--cpus`, new CPUs for a partition or for the parent
  of one, deleting a partition, a restore step that changes one) the preview shows the note above instead.
- With `-v`, `irq-affinity` also lists each IRQ that would change (`IRQ 24: 0-31 -> 0-7,16-23`) and
  `kthread-affinity` each kernel thread (`2 kthreadd: 0-31 -> 0-7,16-31`). Kernel threads that refuse anyway (a race) are
  only known in a real run.
- `restore -n FILE` (or `-n restore FILE`; give the option before FILE) reads and validates the journal and prints
  the undo steps, newest record first; the file is not touched. `restore FILE -n` (option after FILE) is a usage
  error. Restore steps are not preconditions-checked, as in a real restore.
- With `-n -u FILE`, FILE is validated as a real run would: header, 0.5.x format, records, mode, and its owner, which
  must be root because a real run is (a file owned by you is refused). A truncated last line is reported
  (`would drop truncated last line of FILE`), not trimmed. A directory that does not exist fails as in a real run. If
  you cannot read an existing journal (root-owned, mode 0600), the preview says `would record undo in FILE (existing
  journal not readable as this user; checked only in a real run)`.

```sh
vfio-isolate restore -n /run/vfio-isolate.undo
```

- A dry run does not need root where the files it reads are readable by the current user; a value it cannot read is
  shown as `unknown (permission denied)` (or `does not exist`, or the error text). Journals are root-owned and mode 0600, so `restore -n` normally needs root.
- A dry run cannot know what only the kernel decides: whether it can supply the hugepages, which IRQs refuse the new
  affinity (`EIO`), which tasks cannot be moved, and whether a cpuset partition is accepted.

### Error reporting and exit statuses

- IRQs and tasks that cannot be changed do not stop a run. `irq-affinity` and `move-tasks` (and their undo during
  `restore`) count expected failures per kind and print one summary line per kind at the end: kernel-managed IRQs
  cannot be moved, vanished IRQs, kernel threads and exited tasks. With `-v` each item is listed. Any other error is
  printed as a warning naming the item the first time it occurs; further items with the same error are only counted.
- If one `irq-affinity` or `move-tasks` command attempted at least one item, changed none, and at least one failure
  was unexpected, the run continues but ends with status 1 and the line
  `vfio-isolate: <command>: no IRQ could be changed` (or `no task could be moved`).
- A command that fails while it is checked, recorded or executed stops the run with
  `vfio-isolate: <command> failed: <reason>`. The message tells you how to get back: with `-u` and at least one undo
  record written, that `vfio-isolate restore <file>` undoes the changes made so far; without `-u`, once a command has
  started executing, that changes made before the failure remain.
- An unexpected exception prints one line with `use -d for a traceback`; `-d` shows the traceback.
- `-v` enables verbose output, `-d` debug output.

| Status | Meaning |
| ------ | ------- |
| 0 | success |
| 1 | failure, including a run where `irq-affinity` or `move-tasks` changed nothing because of unexpected errors; also a `restore` that kept failed steps |
| 2 | usage error |
| 130 | interrupted (Ctrl-C); before the first change it reports that nothing was changed; with `-u` and records written it prints the restore hint; an interrupted `restore` leaves its file for another `restore` |

## Command reference

All commands are given after the global options `-v`, `-d` and `-u <undo-file>`.

### compact-memory

`vfio-isolate compact-memory`

Asks the kernel to compact memory (writes `1` to `/proc/sys/vm/compact_memory`), which makes huge pages easier to
allocate. Takes no arguments. Nothing to undo.

### cpu-governor

`vfio-isolate cpu-governor GOVERNOR CPUS`

Sets the CPU frequency governor of the given CPUs (`C`, `N` or `M` form). The governor is checked against each CPU's
available governors before anything runs (a governor module that is not loaded is refused; load it first with
`modprobe cpufreq_<name>`). Undo restores each CPU's previous governor.

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo cpu-governor performance C2-5,8-11
```

### cpuset-create

`vfio-isolate cpuset-create [--cpus CPUS] [--mems NODES] NAME`

Creates the cpuset (cgroup) `NAME`, e.g. `/vfio-test`.

- `--cpus CPUS`: CPUs of the cpuset (`C`, `N` or `M` form).
- `--mems NODES`: NUMA memory nodes (`N` form).
- Without `--cpus`/`--mems` the new cpuset inherits its parent's values.
- Refused for systemd units and `/`, and below a systemd unit that does not delegate its subtree (`Delegate=yes`);
  these checks happen before any change. The `cpuset` controller is enabled in the ancestors as needed.
- Undo deletes the cpuset.

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo cpuset-create --cpus C1-4 --mems N0 /vfio-test
```

### cpuset-delete

`vfio-isolate cpuset-delete NAME`

Moves all processes of the cpuset to its parent cpuset, then removes it. Refused for systemd units and `/`. Undo
recreates the cpuset with its previous cpus and mems; the processes are not moved back.

A cpuset that has child cgroups is refused; delete the children first. A cpuset that is briefly busy (new processes
appeared after the move) is retried for about 2 seconds, moving the tasks again, before failing with "still in use".

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo cpuset-delete /vfio-test
```

### cpuset-modify

`vfio-isolate cpuset-modify [--cpus CPUS] [--mems NODES] [--partition member|root|isolated] NAME`

Changes the CPUs, memory nodes and (experimental) partition type of an existing cpuset. Refused for `/`.

- `--cpus CPUS`: CPUs (`C`, `N` or `M` form).
- `--mems NODES`: NUMA memory nodes (`N` form).
- `--partition member|root|isolated`: EXPERIMENTAL, sets the cgroup v2 partition type; see
  [Exclusive CPUs with a partition](#exclusive-cpus-with-a-partition-experimental).
- Systemd units (`*.slice`, `*.scope`, `*.service`, ...): when systemd reports the unit's cgroup as `NAME`, the
  options are applied as runtime unit properties with `systemctl set-property --runtime` (`AllowedCPUs=`,
  `AllowedMemoryNodes=`, `CPUSetPartition=`) instead of writing cgroup files, so systemd stays the owner of the
  cgroup. The setting survives `systemctl daemon-reload`; a value written directly into `cpuset.cpus` of a slice
  would be reset by a reload. If the unit name and systemd's `ControlGroup` disagree, the command fails before any
  change.
- Other cgroups, and hosts without systemd: written directly, after enabling the `cpuset` controller in the ancestors.
- Undo restores the previous configured values (an empty value, meaning inherit from the parent, is restored as
  empty; on the systemd route the previous properties are restored). For a partition, undo restores the previous partition type (on the systemd route a previously unset value is restored as `member`; empty is never restored).

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo cpuset-modify --cpus C0-6,16-22 /system.slice
```

### drop-caches

`vfio-isolate drop-caches`

Drops the page cache, dentries and inodes (writes `3` to `/proc/sys/vm/drop_caches`). Takes no arguments. Nothing to
undo.

### hugepages

`vfio-isolate hugepages [--node N<n>] PAGESIZE AMOUNT`

Adds `AMOUNT` of memory in pages of `PAGESIZE` to the hugepage pool (`nr_hugepages`); the amount is relative to the
current pool size, not a target. Undo releases the same number of pages again, never below zero, whatever else changed the pool meanwhile, so
overlapping VMs that each add and release their own pages are fine. Pages that are still in use are kept by the kernel
until their user exits, so a `restore` while the VM still runs does not break it; they return to the free pool when the
VM is gone.

- `PAGESIZE`: page size as `2M`, `1G` or `2048k`. It must match the page size of the VM (libvirt:
  `<page size=...>` in `<memoryBacking>`). Sizes the kernel does not offer are usage errors.
- `AMOUNT`: memory to add, as `16G`, `512M` and so on; it must be an exact multiple of the page size
  (`hugepages 2M 16G` adds 8192 pages).
- `--node N<n>`: add the pages on one NUMA node instead of system-wide, for example `N0`. Exactly one node, and it
  must have a pool of that size.
- If the kernel provides fewer pages than asked, the command fails with `got 6G of 16G in 1G pages`, releases what it
  got and leaves no undo record, so a `restore` of the same undo file afterwards is safe.
- Runs of vfio-isolate are serialized by a lock (`/run/vfio-isolate.lock`), so two hooks starting at the same time
  do not race on the pool.
- To use the pages, QEMU needs hugepage backing; for libvirt add
  `<memoryBacking><hugepages><page size='2048' unit='KiB'/></hugepages></memoryBacking>` to the domain XML.
  Without hugepage backing, the pool stays unused and only takes memory away from the host.

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo hugepages 2M 16G
```

#### 2M or 1G

Use 2M pages with this command. They allocate at runtime, are taken only while the VM runs and go back to the
host when it stops. Tested on a real host with GPU and NVMe passthrough (`hugepages 2M 16G`, all 8192 pages in use
by the VM) and in a VM with heavily fragmented memory.

1G pages need physically contiguous gigabytes, and at runtime they usually fail:

- On a desktop host after 11 hours of uptime, `hugepages 1G 8G` got 0 of 8 pages with 31 GB free, with and without
  `compact-memory` first. Unmovable and reclaimable kernel memory is spread over all of RAM, so no free gigabyte is
  left.
- `hugetlb_cma=<size>` does not help with passthrough. The kernel reserves the area and this command gets its 1G
  pages from it, but the VM then fails to start with `vfio_container_dma_map(...) = -12 (Cannot allocate memory)`:
  VFIO pins the VM's memory for DMA, the kernel does not allow pinning pages in a CMA area, and it cannot move 1G
  pages out of it. Use it only for VMs without passthrough devices.
- What works is reserving them at boot with `hugepagesz=1G hugepages=N` on the kernel command line, without this
  command. That memory is gone for the host even while the VM is off.

The gain of 1G over 2M pages is one level less of address translation; for a gaming VM it is likely small, and with
transparent hugepages (on by default) the VM already gets 2M pages for much of its memory.

### irq-affinity

`vfio-isolate irq-affinity mask|add CPUS`

Changes the affinity of all active IRQs. It first applies the same operation to `/proc/irq/default_smp_affinity`,
the affinity every IRQ gets when it is created.

- The default matters because IRQs created later start with it: QEMU requests the VFIO IRQs after the libvirt
  `prepare` hook has run, so without it they land on the VM's CPUs.
- A `mask` that would leave no online CPU in the default is refused before anything changes (exit status 1).
- `mask CPUS`: removes the CPUs from each IRQ's affinity. If none would remain, the IRQ gets all other CPUs.
- `add CPUS`: adds the CPUs to each IRQ's affinity.
- Kernel-managed IRQs cannot be moved; they keep their affinity and are summarized (see
  [Error reporting](#error-reporting-and-exit-statuses)).
- Undo restores each IRQ's previous affinity. For the default it is relative: it gives back only the CPUs this run
  removed (or removes only the CPUs it added), so overlapping VMs do not hand each other's CPUs back.
- IRQs created while the VM runs are not journaled: host IRQs created in that window (hotplug, driver reload) keep
  the restricted affinity after the restore. VFIO IRQs disappear with QEMU.
- `irqbalance` rewrites IRQ affinities periodically and so silently undoes this command. If a process named
  `irqbalance` is running, the command prints one warning to stderr per invocation (and still runs). Either stop it
  around the VM (`systemctl stop irqbalance`, start it again afterwards) or ban the VM's CPUs in its configuration with
  `IRQBALANCE_BANNED_CPULIST`. The config file differs by distribution, e.g. `/etc/default/irqbalance` or
  `/etc/sysconfig/irqbalance`. irqbalance automatically avoids CPUs isolated with the kernel parameters `isolcpus=`
  and `nohz_full=` (it reads `/sys/devices/system/cpu/isolated` and `nohz_full`), but most likely not CPUs isolated by
  cpuset partitions: with partitions, set `IRQBALANCE_BANNED_CPULIST` or stop irqbalance. `IRQBALANCE_BANNED_CPUS`
  (a hex mask) is deprecated since irqbalance 1.8.0.

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo irq-affinity mask C2-5,8-11
sudo vfio-isolate irq-affinity add C2-5,8-11
```

### move-tasks

`vfio-isolate move-tasks FROM TO`

Moves all tasks from cpuset `FROM` to cpuset `TO`. Kernel threads and tasks that exited meanwhile are skipped and
summarized. Undo moves back exactly the processes that were in `FROM` when the command ran and are still alive and in
`TO`; processes that were already in `TO` stay. On systemd hosts prefer restricting slices with `cpuset-modify` over
moving processes out of their units, which confuses systemd's accounting.

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo move-tasks /vfio-test /
```

### restore

`vfio-isolate restore UNDO_FILE`

Undoes the runs recorded in the journal, newest first. Continues past failing steps; deletes the file on success,
otherwise keeps only the failed steps and exits with status 1. Cannot be combined with `-u`. See
[Undo journal](#undo-journal).

```sh
sudo vfio-isolate restore /run/vfio-isolate.undo
```

### workqueue-affinity

`vfio-isolate workqueue-affinity mask|add CPUS`

Restricts the CPUs that unbound kernel workqueues (writeback, block I/O, crypto, ...) run on, by
changing `/sys/devices/virtual/workqueue/cpumask`. Per-CPU (bound) kworkers (`kworker/N:...`) cannot be moved and
are not affected.

- `mask CPUS`: removes the CPUs from the mask.
- `add CPUS`: adds the CPUs to the mask.
- The new mask is computed from the last requested mask. A result without any CPU is refused.
- Refused while CPUs are in isolated cpuset partitions: the kernel already keeps unbound workqueues off them, and
  writing the mask would lose them from it when the partition is removed. It is not needed with isolated partitions;
  if combined, put it before the partition step (`workqueue-affinity mask ... cpuset-modify --partition isolated ...`).
- A result without an online CPU is refused.
- Undo restores the previous requested mask, minus the CPUs isolated at that time.

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo workqueue-affinity mask C2-5,8-11
sudo vfio-isolate workqueue-affinity add C2-5,8-11
```

### kthread-affinity

`vfio-isolate kthread-affinity mask|add CPUS`

Keeps kernel threads (`kswapd`, `khugepaged`, `kcompactd`, `jbd2/...`, ...) off the VM's CPUs. Kernel threads stay in
the root cgroup, so cpusets and `move-tasks` cannot do it. The command changes the CPU affinity of `kthreadd`
(PID 2), whose affinity every new kernel thread inherits, and of every kernel thread that accepts a new affinity. It
replaces the `taskset -pc ... 2` workaround of older hook scripts, which had no undo and left running kernel threads
where they were.

- `mask CPUS`: removes the CPUs from each thread's affinity; a thread that would have none left gets all other online CPUs.
- `add CPUS`: adds the CPUs to each thread's affinity.
- The kernel threads are listed when the command line is parsed (threads with `PF_KTHREAD` in `/proc/<pid>/stat`);
  threads created later inherit what `kthreadd` has.
- Per-CPU kernel threads (`ksoftirqd/N`, `kworker/N:...`, `migration/N`, ...; `PF_NO_SETAFFINITY`) always refuse a new
  affinity and are skipped, so they appear neither in the output nor in the undo file. A thread that still refuses
  (`EINVAL`) or that exited meanwhile (`ESRCH`) is only counted (`vfio-isolate: 1 kernel thread exited before it could be
  moved`; with `-v` each thread is listed). Any other error is reported once; the command fails only if no thread
  could be changed because of such an unexpected error.
- Refused while CPUs are in isolated cpuset partitions: the kernel then restricts `kthreadd` itself, and an affinity
  recorded with a partition active would keep kernel threads off those CPUs after the partition is gone. If combined,
  put it before the partition step (`kthread-affinity mask ... cpuset-modify --partition isolated ...`).
- Undo restores each thread's previous affinity. A thread that exited meanwhile, or whose PID now belongs to another
  process or kernel thread (checked by the thread's start time), is left alone and counts as restored. Restore does
  not re-check isolation: if a different isolated partition is active at release, `kthreadd`'s previous affinity is
  restored as recorded (accepted by design).

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo kthread-affinity mask C8-15,24-31
sudo vfio-isolate kthread-affinity add C8-15,24-31
```

## Recipes

### Non-NUMA host with systemd

In this example, an AMD 5950x is partitioned between host and VM. It assumes systemd, which has already created the
cgroups `system.slice` and `user.slice`.

The VM exclusively uses the 8 cores of the second die. The last core of the first die is used for emulation and IO
work, and the first seven are for the host.

```sh
sudo vfio-isolate \
    cpuset-modify --cpus C0-6,16-22 /system.slice \
    cpuset-modify --cpus C0-6,16-22 /user.slice
```

This instructs the two existing cgroups that systemd created to only use the first 7 cores (and their SMT siblings).
To pin the VM cores, use libvirt:

```xml
  <vcpu placement='static'>16</vcpu>
  <iothreads>1</iothreads>
  <cputune>
    <vcpupin vcpu='0' cpuset='8'/>
    <vcpupin vcpu='1' cpuset='24'/>
    <vcpupin vcpu='2' cpuset='9'/>
    <vcpupin vcpu='3' cpuset='25'/>
    <vcpupin vcpu='4' cpuset='10'/>
    <vcpupin vcpu='5' cpuset='26'/>
    <vcpupin vcpu='6' cpuset='11'/>
    <vcpupin vcpu='7' cpuset='27'/>
    <vcpupin vcpu='8' cpuset='12'/>
    <vcpupin vcpu='9' cpuset='28'/>
    <vcpupin vcpu='10' cpuset='13'/>
    <vcpupin vcpu='11' cpuset='29'/>
    <vcpupin vcpu='12' cpuset='14'/>
    <vcpupin vcpu='13' cpuset='30'/>
    <vcpupin vcpu='14' cpuset='15'/>
    <vcpupin vcpu='15' cpuset='31'/>
    <emulatorpin cpuset='7,23'/>
    <iothreadpin iothread='1' cpuset='7,23'/>
    <vcpusched vcpus='0' scheduler='rr' priority='1'/>
    <vcpusched vcpus='1' scheduler='rr' priority='1'/>
    <vcpusched vcpus='2' scheduler='rr' priority='1'/>
    <vcpusched vcpus='3' scheduler='rr' priority='1'/>
    <vcpusched vcpus='4' scheduler='rr' priority='1'/>
    <vcpusched vcpus='5' scheduler='rr' priority='1'/>
    <vcpusched vcpus='6' scheduler='rr' priority='1'/>
    <vcpusched vcpus='7' scheduler='rr' priority='1'/>
    <vcpusched vcpus='8' scheduler='rr' priority='1'/>
    <vcpusched vcpus='9' scheduler='rr' priority='1'/>
    <vcpusched vcpus='10' scheduler='rr' priority='1'/>
    <vcpusched vcpus='11' scheduler='rr' priority='1'/>
    <vcpusched vcpus='12' scheduler='rr' priority='1'/>
    <vcpusched vcpus='13' scheduler='rr' priority='1'/>
    <vcpusched vcpus='14' scheduler='rr' priority='1'/>
    <vcpusched vcpus='15' scheduler='rr' priority='1'/>
    <iothreadsched iothreads='1' scheduler='fifo' priority='98'/>
  </cputune>
```

### Exclusive CPUs with a partition (EXPERIMENTAL)

`cpuset-modify --partition member|root|isolated` sets the cgroup v2 partition type. An `isolated` partition has no
load balancing at all, not even among its own CPUs, so every thread running in it must be pinned (vCPUs, emulator and
iothreads). That is stronger than a `root` partition, which only removes its CPUs from the scheduler domains of
others. Example: isolate
the CPUs of the VM in `machine.slice`. The partition must contain every CPU the VM's threads are pinned to, including
`emulatorpin` and `iothreadpin`; the recipe's XML pins those to 7,23, so the partition is C7-15,23-31 and the host
slices get C0-6,16-22:

```sh
sudo vfio-isolate -u /run/vfio-isolate.undo \
    cpuset-modify --cpus C0-6,16-22 /init.scope \
    cpuset-modify --cpus C0-6,16-22 /system.slice \
    cpuset-modify --cpus C0-6,16-22 /user.slice \
    cpuset-modify --cpus C7-15,23-31 --partition isolated /machine.slice
```

Siblings lose the partition's CPUs from their effective set. On kernel 7.2 that also holds for a sibling with explicitly
configured overlapping CPUs (tested); older kernels may refuse the partition then, so restricting the other slices first
as shown is the safe order. The kernel validates the
partition; if it ends up `invalid`, the tool reports the reason and exits with status 1, and `restore` repairs it.
Undo restores the previous partition type (on the systemd route a previously unset value is restored as `member`, never empty). On
systemd units, `root` and `isolated` need `--cpus` unless the unit already has `AllowedCPUs`. If the installed systemd
does not support `CPUSetPartition=`, the command fails before any change.

Pin vCPUs only to CPUs inside the partition. This recipe has not been tested with a running libvirt VM: the partition
itself is tested in a VM, but how libvirt's per-vCPU pinning behaves inside an isolated `machine.slice` is not.

### libvirt hook

Fully featured example, `/etc/libvirt/hooks/qemu` (make it executable). The undo file lives in libvirt's runtime
directory (root only, gone on reboot). If the isolation fails in `prepare`, the hook restores what was already changed
and exits non-zero, so libvirt does not start the VM; libvirt still calls `release` afterwards, which only restores
when the undo file exists.

```sh
#!/bin/bash

# change to your libvirt domain name
VM=win10
[ "$1" = "$VM" ] || exit 0

HCPUS=0-6,16-22
MCPUS=8-15,24-31

UNDOFILE=/run/libvirt/qemu/vfio-isolate-$VM.undo

enable_isolation () {
    # VM backed by hugepages? Add "hugepages 2M 16G \" as its own line after
    # the "compact-memory \" line below.
    vfio-isolate \
        -u $UNDOFILE \
        drop-caches \
        cpu-governor performance C$MCPUS \
        cpuset-modify --cpus C$HCPUS /system.slice \
        cpuset-modify --cpus C$HCPUS /user.slice \
        compact-memory \
        irq-affinity mask C$MCPUS \
        workqueue-affinity mask C$MCPUS \
        kthread-affinity mask C$MCPUS
}

disable_isolation () {
    if [ -e "$UNDOFILE" ]; then
        vfio-isolate restore $UNDOFILE
    fi
}

case "$2" in
"prepare")
    if ! enable_isolation; then
        if [ -e "$UNDOFILE" ]; then
            vfio-isolate restore $UNDOFILE
        fi
        exit 1
    fi
    ;;
"started")
    ;;
"release")
    disable_isolation
    ;;
esac
```

#### AppArmor (Ubuntu)

On Ubuntu the libvirtd AppArmor profile may block the hook from running `vfio-isolate`. Allow it in
`/etc/apparmor.d/local/usr.sbin.libvirtd` with a line like the following (use the path printed by
`command -v vfio-isolate`), then reload the profile with `sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.libvirtd`:

```
/usr/local/bin/vfio-isolate rmix,
```

Reported by users (#4), not tested by this project.

## Testing

`pip install -e '.[test]'` and `pytest` run the unit tests against a fake cgroup tree. The `tests/vm` suite runs the
real CLI against a real kernel and systemd inside a throwaway QEMU VM (the host kernel, root file system read-only
with an in-memory overlay). It needs virtme-ng (`sudo pacman -S virtme-ng` or the distribution equivalent) and
`/dev/kvm`:

```sh
scripts/vm-test --venv /path/to/venv
```

Use a venv in which `pip install -e '.[test]'` has been done. The run takes about 10 seconds; extra arguments are
passed to pytest. Nothing is run as root on the host.
