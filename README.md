# vfio-isolate

vfio-isolate is a command linux tool for Linux, which aims to facilitate CPU and
memory isolation for running virtual machines with guaranteed latency.

```
Usage: vfio-isolate [OPTIONS] COMMAND1 [ARGS]... [COMMAND2 [ARGS]...]...

Options:
  -v, --verbose  enable verbose output
  -d, --debug    enable debug output
  --help         Show this message and exit.

Commands:
  compact-memory  compact memory
  cpuset-create   create a cpuset
  cpuset-delete   delete a cpuset
  drop-caches     drop caches
  move-tasks      move tasks between cpusets
```

#### Usage

To create two distinct cpusets, one for the host on CPU 0-1 (host.slice), 
and one for the machine with cpu 2-5 (machine.slice), and then
move all existing processes to the host.slice, issue this command:  

```
 sudo vfio-isolate \ 
    cpuset-create --cpus C0-1 /host.slice \
    cpuset-create --cpus C2-5 -ce /machine.slice \ 
    move-tasks / /host.slice
```

The `-ce` parameter sets the CPUs to be used exclusively by this cpuset.

To undo the previous command:

```
 sudo vfio-isolate \ 
    cpuset-delete /host.slice \
    cpuset-delete /machine.slice 
```

All processes in a cpuset will be moved to its parent cpuset upon deletion.

If you have a system with more than one NUMA nodes, you might want to isolate according to the different nodes.
For example, on an AMD Threadripper 1920X (12 core, 24 thread), which has 2 NUMA nodes, you could issue

```
 sudo vfio-isolate \ 
    cpuset-create --cpus N0 --mems N0 -mm /host.slice \
    cpuset-create --cpus N1 --mems N1 -ce -me -mm /machine.slice \ 
    move-tasks / /host.slice
```

This will configure NUMA Node 0, in this case CPU 0-5,12-17 for the host, while configuring NUMA node 1 for 
the VM (6-11,18-23). The `-ce` parameter sets the memory of NUMA node 1 to be used exclusively by the cpuset, 
while the `-mm` parameter enables memory migration, so that processes moving to this cpuset will 
have their memory migrated to that node.

