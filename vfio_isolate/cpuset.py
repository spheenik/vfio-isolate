import os
import re

import psutil

from vfio_isolate import fsroot, output
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet
from vfio_isolate.output import *

_HINT = "cgroup v1 users need vfio-isolate 0.5.x"


class HostUnsupportedError(Exception):
    pass


class PartitionInvalidError(Exception):
    """The kernel reports the partition as invalid after it was set; args[0] is the reason."""


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
        """Create the cgroup. Without cpus/mems the files stay empty (inherit from the parent)."""
        self.ensure_controller_path()
        os.mkdir(self.__path())
        self.on_create()
        if cpus:
            self.set_cpus(cpus)
        if mems:
            self.set_mems(mems)

    def exists(self) -> bool:
        return os.path.isdir(self.__path())

    def children(self):
        """Names of the child cgroups (subdirectories), sorted."""
        base = self.__path()
        return sorted(self.name().rstrip("/") + "/" + d for d in os.listdir(base)
                      if os.path.isdir(os.path.join(base, d)))

    def remove(self):
        os.rmdir(self.__path())

    def parents(self):
        """Yield the ancestors from the root down to this cgroup's parent."""
        for n in range(len(self.path)):
            yield CPUSet(self.path[0:n])

    def on_create(self):
        pass

    def ensure_controller_path(self):
        """Enable cpuset in subtree_control of every ancestor (root first); never the target's own."""
        for ancestor in self.parents():
            with ancestor.open("cgroup.subtree_control", "r") as f:
                enabled = f.read().split()
            if "cpuset" not in enabled:
                with ancestor.open("cgroup.subtree_control", "w") as f:
                    f.write("+cpuset")

    @staticmethod
    def _value(mask) -> str:
        # an empty value must be written as "\n": writing "" does not reach the kernel
        return mask.to_list_form() if mask else "\n"

    def get_cpus(self) -> CPUNodeSet:
        """Effective CPUs."""
        with self.open("cpuset.cpus.effective", "r") as f:
            return CPUNodeSet(f.read())

    def _read_configured(self, name: str) -> str:
        """Read a configured cpuset file; a missing file (controller not yet enabled on the
        path) reads as empty. Reading never enables anything."""
        try:
            with self.open(name, "r") as f:
                return f.read()
        except FileNotFoundError:
            return "\n"

    def get_configured_cpus(self) -> CPUNodeSet:
        return CPUNodeSet(self._read_configured("cpuset.cpus"))

    def set_cpus(self, mask: CPUNodeSet):
        self.ensure_controller_path()
        with self.open("cpuset.cpus", "w") as f:
            f.write(self._value(mask))

    def get_mems(self) -> NUMANodeSet:
        """Effective memory nodes."""
        with self.open("cpuset.mems.effective", "r") as f:
            return NUMANodeSet(f.read())

    def get_configured_mems(self) -> NUMANodeSet:
        return NUMANodeSet(self._read_configured("cpuset.mems"))

    def set_mems(self, mask: NUMANodeSet):
        self.ensure_controller_path()
        with self.open("cpuset.mems", "w") as f:
            f.write(self._value(mask))

    def get_partition(self):
        """Return (type, invalid_reason). "isolated invalid (xyz)" -> ("isolated", "xyz");
        reason is None when the partition is valid. A missing file (controller not yet
        enabled on the path) reads as "member"."""
        text = self._read_configured("cpuset.cpus.partition").strip() or "member"
        m = re.fullmatch(r"(\S+)(\s+invalid(?:\s*\((.*)\))?)?", text, re.S)
        if not m:
            return text, None
        return m.group(1), (m.group(3) or "") if m.group(2) else None

    def set_partition(self, partition: str):
        """Write the partition type, read it back and raise PartitionInvalidError if invalid."""
        self.ensure_controller_path()
        with self.open("cpuset.cpus.partition", "w") as f:
            f.write(partition)
        self.verify_partition(partition)

    def verify_partition(self, requested: str):
        """Raise PartitionInvalidError unless the kernel reports a valid partition of the requested type."""
        actual, reason = self.get_partition()
        if reason is not None:
            raise PartitionInvalidError(reason)
        if actual != requested:
            raise PartitionInvalidError(f"kernel reports {actual}, requested {requested}")

    def pids(self):
        with self.open("cgroup.procs", "r") as f:
            for pid in f:
                yield int(pid.strip())

    def add_pid(self, pid: int, silent=False, report=True):
        try:
            if not silent:
                print_verbose(f"moving PID {pid} to CPUSet {self.name()}")
            with self.open("cgroup.procs", "w") as f:
                f.write(str(pid))
            if report:
                output.failures.ok()
            return True
        except OSError as e:
            try:
                name = psutil.Process(pid).name()
            except psutil.NoSuchProcess:
                name = "not running"
            if report:
                output.failures.task(pid, name, e)
            print_debug(f"unable to move PID {pid} ({name}) to CPUSet {self.name()}")
            return False

    def add_all_from_cpuset(self, other, report=True):
        print_verbose(f"moving all processes from CPUSet {other.name()} to CPUSet {self.name()}")
        for pid in other.pids():
            self.add_pid(pid, True, report)
