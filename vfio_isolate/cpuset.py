import os
import re

import psutil

from vfio_isolate import fsroot
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet
from vfio_isolate.output import *

_HINT = "cgroup v1 users need vfio-isolate 0.5.x"


class HostUnsupportedError(Exception):
    pass


_cgroup_root_cache = None


def reset_cgroup_cache():
    global _cgroup_root_cache
    _cgroup_root_cache = None


def _decode_mount_field(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def cgroup_root() -> str:
    """Return the (fsroot-resolved) path of the cgroup v2 mount with the cpuset controller.

    Raises HostUnsupportedError if the host does not qualify. Only successes are cached.
    """
    global _cgroup_root_cache
    if _cgroup_root_cache is not None:
        return _cgroup_root_cache

    v2_mounts = []
    try:
        with open(fsroot.path("proc/self/mounts"), "r") as f:
            lines = f.read().splitlines()
    except OSError as e:
        raise HostUnsupportedError(f"cannot read mount table ({e}); {_HINT}")
    for line in lines:
        fields = line.split()
        if len(fields) < 4:
            continue
        mountpoint = _decode_mount_field(fields[1])
        fstype = fields[2]
        options = fields[3].split(",")
        if fstype == "cgroup" and "cpuset" in options:
            raise HostUnsupportedError(
                f"the cpuset controller is bound to a cgroup v1 hierarchy ({mountpoint}); {_HINT}")
        if fstype == "cgroup2":
            v2_mounts.append(mountpoint)

    if not v2_mounts:
        raise HostUnsupportedError(f"cgroup v2 not found; {_HINT}")
    mountpoint = "/sys/fs/cgroup" if "/sys/fs/cgroup" in v2_mounts else v2_mounts[0]
    root = fsroot.path(mountpoint)

    try:
        with open(root + "/cgroup.controllers", "r") as f:
            controllers = f.read().split()
    except OSError as e:
        raise HostUnsupportedError(f"cannot read cgroup.controllers in {mountpoint} ({e}); {_HINT}")
    if "cpuset" not in controllers:
        raise HostUnsupportedError(f"cpuset controller not available in cgroup v2 at {mountpoint}; {_HINT}")

    _cgroup_root_cache = root
    return root


class CPUSet:

    def __init__(self, name=None):
        if not name:
            self.path = []
        elif isinstance(name, str):
            self.path = list(filter(None, name.split("/")))
        elif isinstance(name, list):
            self.path = [str(x) for x in name]
        else:
            raise Exception("cannot initialize CPUSet")

    def __repr__(self):
        return f"{self.__class__} {self.name()}"

    def __path(self, path: str = None):
        elements = [cgroup_root()]
        elements.extend(self.path)
        if path:
            elements.append(path)
        return "/".join(elements)

    def open(self, file, mode='r'):
        return open(self.__path(file), mode)

    def name(self):
        return "/" + "/".join(self.path)

    def parent(self):
        if not self.path:
            raise Exception("no parent")
        else:
            return CPUSet(self.path[:-1])

    def create(self, cpus: CPUNodeSet = None, mems: NUMANodeSet = None):
        os.mkdir(self.__path())
        self.on_create()
        if cpus:
            self.set_cpus(cpus)
        else:
            self.set_cpus(self.parent().get_cpus())
        if mems:
            self.set_mems(mems)
        else:
            self.set_mems(self.parent().get_mems())

    def exists(self) -> bool:
        return os.path.isdir(self.__path())

    def remove(self):
        os.rmdir(self.__path())

    def parents(self):
        n = 0
        while n < len(self.path):
            yield CPUSet(self.path[0:n])

    def on_create(self):
        pass

    def is_controller_enabled(self, controller):
        with self.open("cgroup.controllers", "r") as f:
            for c in f:
                if controller == c:
                    return True
        return False

    def enable_controller(self, controller, enable=True):
        prefix = "+" if enable else "-"
        with self.open("cgroup.subtree_control", "w") as f:
            f.write(f"{prefix}{controller}")

    def ensure_cpuset_controller_enabled(self):
        if not self.is_controller_enabled("cpuset"):
            self.enable_controller("cpuset")

    def get_cpus(self) -> CPUNodeSet:
        self.ensure_cpuset_controller_enabled()
        with self.open("cpuset.cpus.effective", "r") as f:
            return CPUNodeSet(f.read())

    def set_cpus(self, mask: CPUNodeSet):
        self.ensure_cpuset_controller_enabled()
        with self.open("cpuset.cpus", "w") as f:
            f.write(mask.to_list_form())

    def get_mems(self) -> NUMANodeSet:
        self.ensure_cpuset_controller_enabled()
        with self.open("cpuset.mems.effective", "r") as f:
            return NUMANodeSet(f.read())

    def set_mems(self, mask: NUMANodeSet):
        self.ensure_cpuset_controller_enabled()
        with self.open("cpuset.mems", "w") as f:
            f.write(mask.to_list_form())

    def pids(self):
        with self.open("cgroup.procs", "r") as f:
            for pid in f:
                yield int(pid.strip())

    def add_pid(self, pid: int, silent=False):
        try:
            if not silent:
                print_verbose(f"moving PID {pid} to CPUSet {self.name()}")
            with self.open("cgroup.procs", "w") as f:
                f.write(str(pid))
            return True
        except OSError:
            try:
                name = psutil.Process(pid).name()
            except psutil.NoSuchProcess:
                name = "not running"
            print_debug(f"unable to move PID {pid} ({name}) to CPUSet {self.name()}")
            return False

    def add_all_from_cpuset(self, other):
        print_verbose(f"moving all processes from CPUSet {other.name()} to CPUSet {self.name()}")
        for pid in other.pids():
            self.add_pid(pid, True)
