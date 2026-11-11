## 1. cpuset-delete

- [x] 1.1 `can_execute` refuses cpusets with child cgroups (naming them)
- [x] 1.2 `EBUSY` retry loop (re-move tasks, 50 ms sleep, 2 s deadline, then "still in use" error); other errnos not retried
- [x] 1.3 Unit tests: child cgroup refused before any change; EBUSY once then success; EBUSY always → exit 1 with message (patch time/sleep to keep the test fast)

## 2. VM test

- [x] 2.1 VM test: `-u j cpuset-modify --cpus C0-3 /user.slice` via systemd (AllowedCPUs set, effective 0-3), survives `systemctl daemon-reload`, `restore j` returns it to unrestricted
- [x] 2.2 VM test: `cpuset-delete` of a cgroup with a child is refused; normal delete still works

## 3. README

- [x] 3.1 Remove the X3D note; add "Choosing CPUs" section per design (sysfs commands, rule of thumb, untested marks)
- [x] 3.2 AppArmor paragraph in the libvirt hook recipe
- [x] 3.3 README `cpuset-delete` section: child cgroups refused, busy retry; CHANGELOG: Fixed entry for #9, New entry for the CPU section
- [x] 3.4 Full default suite and VM suite pass
