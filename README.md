# vfio-isolate

vfio-isolate is a command linux tool for Linux, which aims to facilitate CPU and
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
  drop-caches     drop caches
  irq-affinity    manipulate the IRQ affinity
  move-tasks      move tasks between cpusets
  restore         restore a previous state using an undo file
```

#### Usage

To "partion" your CPU between the host and your VM, a mechanism of the Linx kernel, named "cpusets" is used.
Cpusets define the subset of cores are allowed to be scheduled on, but also have some other properties:

| Feature | Description |
| --- | --- |
|cpu-exclusivity| prevents other sibling cpusets to use the cpus of this cpuset|
|mem-exclusivity| prevents other sibling cpusets to use the memory (NUMA) of this cpuset|
|mem-migration| only effective on NUMA systems: when enabled, processes in this cpuset will have their memory migrated to the node they are running on |
|scheduler-load-balance | when enabled, the scheduler will try to load balance processes within the available cpus |

For more information, see the kernel documentation at https://www.kernel.org/doc/Documentation/cgroup-v1/cpusets.txt

#### Non NUMA example

In this example, we have a 6 core, 12 thread CPU from Intel, and we want to leave the first 2 cores for host, IO and
emulation work, while giving the remaining 4 cores to the VM.

The command to use would be this:

```
 sudo vfio-isolate \ 
    cpuset-create --cpus C0-1,6-7 /host.slice \
    cpuset-create --cpus C0-11 -nlb /machine.slice \ 
    move-tasks / /host.slice
```

Notice that scheduler-load-balancing has been disabled on the machine.slice, and that there is some overlap between 
the two cpusets (so cpu exclusivity cannot be used), and you have to use pinning
in libvirt to pin the guest cpus like this:

```
<vcpu placement='static' cpuset='0-11'>8</vcpu>
  <vcpupin vcpu="0" cpuset="2"/>
  <vcpupin vcpu="1" cpuset="8"/>
  <vcpupin vcpu="2" cpuset="3"/>
  <vcpupin vcpu="3" cpuset="9"/>
  <vcpupin vcpu="4" cpuset="4"/>
  <vcpupin vcpu="5" cpuset="10"/>
  <vcpupin vcpu="4" cpuset="5"/>
  <vcpupin vcpu="5" cpuset="11"/>
  <emulatorpin cpuset="0-1,6-7"/>
  <iothreadpin iothread="1" cpuset="0-1,6-7"/>
</cputune>
```

To manually undo the previous command:

```
 sudo vfio-isolate \ 
    cpuset-delete /host.slice \
    cpuset-delete /machine.slice 
```

Or you could use the undo feature built into vfio-isolate (see below).

All processes in a cpuset will be moved to its parent cpuset upon deletion.

#### NUMA example

If you have a system with more than one NUMA nodes, you might want to isolate according to the different nodes.
For example, on an AMD Threadripper 1920X (12 core, 24 thread), which has 2 NUMA nodes, you could do the following

```
 sudo vfio-isolate \ 
    cpuset-create --cpus N0 --mems N0 -mm /host.slice \
    cpuset-create --cpus N1 --mems N1 -ce -me -mm -nlb /machine.slice \ 
    move-tasks / /host.slice
```

This will configure NUMA Node 0, in this case CPU 0-5,12-17 for the host, while configuring NUMA node 1 for 
the VM (6-11,18-23). The `-ce/-me` parameters sets the cpus/memory of NUMA node 1 to be used exclusively by this cpuset, 
while the `-mm` parameter enables memory migration for both sets, so that processes moving into either cpuset will 
have their memory migrated to the right node. Further `-nlb` disables scheduler load balancing.

#### Undo

vfio-isolate is able to record all the changes that it did and storing a recipe to undo them into a file, to be executed
later.

```
 sudo vfio-isolate -u /tmp/undo_description \ 
    cpuset-create --cpus C1-4 /test.slice
```

This will create the `test.slice` cpuset, and also a file `/tmp/undo_description` that when executed like this

```
 sudo vfio-isolate restore /tmp/undo_description
```

will remove `test.slice`. This works with all the subcommands that vfio-isolate supports. 

#### IRQ affinity

vfio-isolate contains basic support for disabling IRQ handler execution on certain cpus:

```
 sudo vfio-isolate -u /tmp/undo_irq irq-affinity mask C2-5,8-11
```

will prevent IRQ execution on the mentioned cpuset.
It will also write an undo description in `/tmp/undo_irq` which can be used to restore the previous state:

```
 sudo vfio-isolate restore /tmp/undo_irq
```

#### setting CPU governor

vfio-isolate contains basic support for setting the CPU frequency governor for selected CPUs:

```
 sudo vfio-isolate -u /tmp/undo_gov cpu-governor performance C2-5,8-11
```

will set the mentioned CPUs to performance mode.
It will also write an undo description in `/tmp/undo_gov` which can be used to restore the previous state:

```
 sudo vfio-isolate restore /tmp/undo_gov
```

   

