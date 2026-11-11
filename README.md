#### Note: If you're looking for solutions on how to work with the new AMD 79x0X3D models, see [this issue](https://github.com/spheenik/vfio-isolate/issues/14).

# vfio-isolate

vfio-isolate is a command line tool for Linux, which aims to facilitate CPU and
memory isolation for running virtual machines with guaranteed latency.

```
Usage: vfio-isolate [OPTIONS] COMMAND1 [ARGS]... [COMMAND2 [ARGS]...]...

Options:
  -v, --verbose                enable verbose output
  -d, --debug                  enable debug output
  -u, --undo-file <undo-file>  Create a file that describes the operations
                               needed to undo

  --help                       Show this message and exit.

Commands:
  compact-memory  compact memory
  cpu-governor    set the CPU governor for the given CPUs
  cpuset-create   create a cpuset
  cpuset-delete   delete a cpuset
  cpuset-modify   modify a cpuset
  drop-caches     drop caches
  irq-affinity    manipulate the IRQ affinity
  move-tasks      move tasks between cpusets
  restore         restore a previous state using an undo file
```

#### Usage

vfio-isolate 0.6 and newer requires cgroup v2 (the unified hierarchy) with the `cpuset` controller available.
If your system still uses cgroup v1, stay on 0.5.2: `pip install vfio-isolate==0.5.2`.

To "partion" your CPU between the host and your VM, a mechanism of the Linx kernel, named "cgroups" is used.

CPU sets are part of cgroups, and define the subset of cores processes in a cgroup are allowed to be scheduled on.

#### Non NUMA example (cgroups v2)

In this example, an AMD 5950x is partitioned between host and VM. 
The example further assumes that you are using
systemd, which has created the cgroups system.slice and user.slice already.

The VM is configured so that it exclusively uses the 8 cores of the second die.
The last core of the first die is used for emulation and IO work, and the first seven are for the host.

The command to use would be this:

```
 sudo vfio-isolate \ 
    cpuset-modify --cpus C0-6,16-22 /system.slice \
    cpuset-modify --cpus C0-6,16-22 /user.slice
```

This will instruct the two existing cgroups that systemd created to only use the first 7 cores.
To pin the VM cores, use libvirt:

```
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

#### systemd hosts

On hosts running systemd, `cpuset-modify` on a systemd unit (`*.slice`, `*.scope`, `*.service`, ...) does not write
to the cgroup files. It runs `systemctl set-property --runtime <unit> AllowedCPUs=... AllowedMemoryNodes=...
CPUSetPartition=...` instead, so systemd stays the owner of that cgroup. The setting survives `systemctl
daemon-reload`; a value written directly into `cpuset.cpus` of a slice would be silently reset by a reload, losing
the isolation. `restore` resets the properties through systemd as well.

- Prefer restricting slices (`cpuset-modify` on `/system.slice`, `/user.slice`, `/init.scope`) over `move-tasks` on
  systemd hosts: moving processes out of their units confuses systemd's accounting.
- `cpuset-create` and `cpuset-delete` are refused for systemd units, and `cpuset-create` is refused below a systemd
  unit that is not delegated (`Delegate=yes`), because systemd owns those cgroups.
- Cgroups that systemd does not manage (for example `/mygroup`) are written directly; the `cpuset` controller is
  enabled in their ancestors as needed.
- Without `--cpus`/`--mems` a new cpuset inherits its parent's values.

#### Exclusive CPUs with a partition (EXPERIMENTAL)

`cpuset-modify --partition [member|root|isolated]` sets the cgroup v2 partition type. An `isolated` partition removes
its CPUs from the scheduler domains of everything else, which is stronger than plain restriction. Example: isolate
the CPUs of the VM in `machine.slice`:

```
 sudo vfio-isolate -u /tmp/undo_partition \
    cpuset-modify --cpus C0-6,16-22 /init.scope \
    cpuset-modify --cpus C0-6,16-22 /system.slice \
    cpuset-modify --cpus C0-6,16-22 /user.slice \
    cpuset-modify --cpus C8-15,24-31 --partition isolated /machine.slice
```

Restricting the other top-level slices first is not required: the kernel removes the partition's CPUs from the
effective CPUs of the siblings anyway. It is shown for clarity about where host work runs. The kernel validates the
partition; if it ends up `invalid`, the tool reports the reason and exits with status 1, and `restore` repairs it.
Undo restores the previous partition type (on the systemd route, a previously unset value is restored as `member`).

Pin vCPUs only to CPUs inside the partition. How libvirt's own per-vCPU cpuset handling behaves inside an isolated
`machine.slice` is untested.

#### Undo

vfio-isolate is able to record all the changes that it did and storing a recipe to undo them into a journal file, to be
executed later. The journal is a plain text file (JSON Lines) that is written before each change is made, so it is
complete even if a run fails half way.

```
 # vfio-isolate -u /tmp/undo_description \ 
    cpuset-create --cpus C1-4 /test.slice
```

This will create the `test.slice` cpuset, and also a file `/tmp/undo_description` that when executed like this

```
 # vfio-isolate restore /tmp/undo_description
```

will remove `test.slice`. This works with all the subcommands that vfio-isolate supports. 

- If the undo file already exists and is a journal, later runs with `-u` append to it. `restore` then undoes every
  recorded run, newest first, back to the state before the first one.
- `restore` continues past steps that fail and reports them on stderr. If everything succeeded the file is deleted;
  otherwise it is rewritten to contain only the failed steps, and the exit status is non-zero, so you can fix the problem
  and run `restore` again.
- The file is created with mode 0600. Symlinks, files not owned by you and files writable by others are refused.
  `-u` and `restore` can not be used in the same command.
- Undo files written by vfio-isolate 0.5.x are not supported and are refused. Run `restore` with 0.5.2
  (`pip install vfio-isolate==0.5.2`) for any VM prepared with 0.5.x before upgrading.

#### Deleting a cpuset

```
 # vfio-isolate cpuset-delete /test.slice
```

All processes in the cpuset are moved to its parent cpuset, then the cpuset is removed. With `-u`, the undo file
recreates the cpuset and restores its cpus and mems (the processes are not moved back).

#### IRQ affinity

vfio-isolate contains basic support for disabling IRQ handler execution on certain cpus:

```
 # vfio-isolate -u /tmp/undo_irq irq-affinity mask C2-5,8-11
```

will prevent IRQ execution on the mentioned cpuset.
It will also write an undo description in `/tmp/undo_irq` which can be used to restore the previous state:

```
 # vfio-isolate restore /tmp/undo_irq
```

#### setting CPU governor

vfio-isolate contains basic support for setting the CPU frequency governor for selected CPUs:

```
 # vfio-isolate -u /tmp/undo_gov cpu-governor performance C2-5,8-11
```

will set the mentioned CPUs to performance mode.
It will also write an undo description in `/tmp/undo_gov` which can be used to restore the previous state:

```
 # vfio-isolate restore /tmp/undo_gov
```

#### Fully featured example (/etc/libvirt/hooks/qemu):

```
#!/bin/bash

HCPUS=0-6,16-22
MCPUS=8-15,24-31

UNDOFILE=/var/run/libvirt/qemu/vfio-isolate-undo.bin

disable_isolation () {
	vfio-isolate \
		restore $UNDOFILE

	taskset -pc 0-31 2  # kthreadd reset
}

enable_isolation () {
	vfio-isolate \
		-u $UNDOFILE \
		drop-caches \
		cpu-governor performance \
		cpuset-modify --cpus C$HCPUS /system.slice \
		cpuset-modify --cpus C$HCPUS /user.slice \
		compact-memory \
		irq-affinity mask C$MCPUS

	taskset -pc $HCPUS 2  # kthreadd only on host cores
}

case "$2" in
"prepare")
	enable_isolation
	;;
"started")
	;;
"release")
	disable_isolation
	;;
esac
```

#### Running the tests

`pip install -e '.[test]'` and `pytest` run the unit tests against a fake cgroup tree. The `tests/vm` suite runs the
real CLI against a real kernel and systemd inside a throwaway QEMU VM (the host kernel, root file system read-only
with an in-memory overlay). It needs virtme-ng (`sudo pacman -S virtme-ng` or the distribution equivalent) and
`/dev/kvm`:

```
 scripts/vm-test --venv /path/to/venv      # a venv with 'pip install -e .[test]' done in it
```

It takes a few minutes; extra arguments are passed to pytest. Nothing is run as root on the host.
