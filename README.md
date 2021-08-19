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

To "partion" your CPU between the host and your VM, a mechanism of the Linx kernel, named "cgroups" is used.
There exist 2 versions of cgroup, v1 and v2. Some options are only available for cgroups v1.

To find out what version your system is using use the following command

```
mount | grep cgroup
```

it will show type cgroup for v1, and cgroup2 vor v2.

CPU sets are part of cgroups, and define the subset of cores processes in a cgroup are allowed to be scheduled on.

For cgroups v1, they also have some other properties:

| Feature | Description |
| --- | --- |
|cpu-exclusivity| prevents other sibling cpusets to use the cpus of this cpuset|
|mem-exclusivity| prevents other sibling cpusets to use the memory (NUMA) of this cpuset|
|mem-migration| only effective on NUMA systems: when enabled, processes in this cpuset will have their memory migrated to the node they are running on |
|scheduler-load-balance | when enabled, the scheduler will try to load balance processes within the available cpus |

For more information, see the kernel documentation at https://www.kernel.org/doc/Documentation/cgroup-v1/cpusets.txt

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

#### Non NUMA example (cgroups v1)

In this example, we have a 6 core, 12 thread CPU from Intel, and we want to leave the first 2 cores for host, IO and
emulation work, while giving the remaining 4 cores to the VM.

The command to use would be this:

```
 # vfio-isolate \ 
    cpuset-create --cpus C0-1,6-7 /host.slice \
    move-tasks / /host.slice
```

This will move all the processes from the root cgroup to your newly created host.slice, and assigns only the first two 
physical cores for execution.

To now make your VM use the now remaining idle cores, you can use libvirt:
```
<vcpu placement='static'>8</vcpu>
  <vcpupin vcpu="0" cpuset="2"/>
  <vcpupin vcpu="1" cpuset="8"/>
  <vcpupin vcpu="2" cpuset="3"/>
  <vcpupin vcpu="3" cpuset="9"/>
  <vcpupin vcpu="4" cpuset="4"/>
  <vcpupin vcpu="5" cpuset="10"/>
  <vcpupin vcpu="6" cpuset="5"/>
  <vcpupin vcpu="7" cpuset="11"/>
  <emulatorpin cpuset="0-1,6-7"/>
  <iothreadpin iothread="1" cpuset="0-1,6-7"/>
</cputune>
```

To manually undo the previous command:

```
 sudo vfio-isolate \ 
    cpuset-delete /host.slice
```

Or you could use the undo feature built into vfio-isolate (see below).

All processes in a cpuset will be moved to its parent cpuset upon deletion.

#### NUMA example (cgroups v1)

If you have a system with more than one NUMA nodes, you might want to isolate according to the different nodes.
For example, on an AMD Threadripper 1920X (12 core, 24 thread), which has 2 NUMA nodes, you could do the following

```
 # vfio-isolate \ 
    cpuset-create --cpus N0 --mems N0 -mm /host.slice \
    move-tasks / /host.slice
```

This will configure NUMA Node 0, in this case CPU 0-5,12-17 for the host, while configuring NUMA node 1 for 
the VM (6-11,18-23). The `-mm` parameter enables memory migration, so that processes moving into either the host or
the VM cpuset will have their memory migrated to the right node.

#### Undo

vfio-isolate is able to record all the changes that it did and storing a recipe to undo them into a file, to be executed
later.

```
 # vfio-isolate -u /tmp/undo_description \ 
    cpuset-create --cpus C1-4 /test.slice
```

This will create the `test.slice` cpuset, and also a file `/tmp/undo_description` that when executed like this

```
 # vfio-isolate restore /tmp/undo_description
```

will remove `test.slice`. This works with all the subcommands that vfio-isolate supports. 

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

   

