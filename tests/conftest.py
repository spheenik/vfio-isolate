import shutil
from pathlib import Path

import pytest

from vfio_isolate import fsroot

NUM_CPUS = 8
CONTROLLERS = "cpuset cpu io memory pids"

_UNRELATED_MOUNTS = [
    "proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0",
    "sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0",
    "tmpfs /run tmpfs rw,nosuid,nodev,size=1600000k,mode=755 0 0",
]
_V2_STD = "cgroup2 /sys/fs/cgroup cgroup2 rw,nosuid,nodev,noexec,relatime,nsdelegate 0 0"
_V2_NONSTD = "cgroup2 /mnt/cg2 cgroup2 rw,nosuid,nodev,noexec,relatime,nsdelegate 0 0"
_V2_UNIFIED = "cgroup2 /sys/fs/cgroup/unified cgroup2 rw,nosuid,nodev,noexec,relatime,nsdelegate 0 0"
_V1_CPUSET = "cgroup /sys/fs/cgroup/cpuset cgroup rw,nosuid,nodev,noexec,relatime,cpuset 0 0"

LAYOUTS = ("v2", "v2-nonstandard", "hybrid", "v1", "no-cpuset", "none")


class FakeHost:
    """A fake /proc + /sys tree rooted in a tmp dir; fsroot.ROOT points at it."""

    def __init__(self, root: Path):
        self.root = root
        self.layout = None
        self.cgroup_mount = None  # absolute (fake-host) path of the cgroup2 mount, if any
        self._build_static()
        self.set_layout("v2")

    # -- static sysfs/procfs parts -------------------------------------------------
    def _write(self, rel, content):
        p = self.root / rel.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def _build_static(self):
        cpu = "sys/devices/system/cpu"
        last = NUM_CPUS - 1
        for n in range(NUM_CPUS):
            (self.root / cpu / f"cpu{n}").mkdir(parents=True, exist_ok=True)
        self._write(f"{cpu}/online", f"0-{last}\n")
        self._write(f"{cpu}/present", f"0-{last}\n")
        self._write(f"{cpu}/possible", f"0-{last}\n")
        node = "sys/devices/system/node"
        self._write(f"{node}/online", "0\n")
        self._write(f"{node}/possible", "0\n")
        self._write(f"{node}/node0/cpulist", f"0-{last}\n")
        (self.root / "proc/irq").mkdir(parents=True, exist_ok=True)
        (self.root / "proc/sys/vm").mkdir(parents=True, exist_ok=True)
        self._write("proc/sys/vm/drop_caches", "0")
        self._write("proc/sys/vm/compact_memory", "0")

    # -- cgroup layouts --------------------------------------------------------------
    def _populate_cgroup_root(self, mount: str, with_cpuset=True):
        d = self.root / mount.lstrip("/")
        d.mkdir(parents=True, exist_ok=True)
        ctl = CONTROLLERS if with_cpuset else CONTROLLERS.replace("cpuset ", "")
        last = NUM_CPUS - 1
        (d / "cgroup.controllers").write_text(ctl + "\n")
        (d / "cgroup.subtree_control").write_text("\n")
        (d / "cgroup.procs").write_text("")
        (d / "cpuset.cpus.effective").write_text(f"0-{last}\n")
        (d / "cpuset.mems.effective").write_text("0\n")

    def set_layout(self, name: str):
        if name not in LAYOUTS:
            raise ValueError(f"unknown layout {name!r}, expected one of {LAYOUTS}")
        # wipe any cgroup trees of a previous layout
        for rel in ("sys/fs/cgroup", "mnt/cg2"):
            shutil.rmtree(self.root / rel, ignore_errors=True)
        lines = list(_UNRELATED_MOUNTS)
        self.cgroup_mount = None
        if name == "v2":
            lines.append(_V2_STD)
            self.cgroup_mount = "/sys/fs/cgroup"
            self._populate_cgroup_root(self.cgroup_mount)
        elif name == "v2-nonstandard":
            lines.append(_V2_NONSTD)
            self.cgroup_mount = "/mnt/cg2"
            self._populate_cgroup_root(self.cgroup_mount)
        elif name == "hybrid":
            lines += [_V2_UNIFIED, _V1_CPUSET]
            self.cgroup_mount = "/sys/fs/cgroup/unified"
            self._populate_cgroup_root(self.cgroup_mount)
            (self.root / "sys/fs/cgroup/cpuset").mkdir(parents=True, exist_ok=True)
        elif name == "v1":
            lines.append(_V1_CPUSET)
            (self.root / "sys/fs/cgroup/cpuset").mkdir(parents=True, exist_ok=True)
        elif name == "no-cpuset":
            lines.append(_V2_STD)
            self.cgroup_mount = "/sys/fs/cgroup"
            self._populate_cgroup_root(self.cgroup_mount, with_cpuset=False)
        elif name == "none":
            pass
        self.layout = name
        self._write("proc/self/mounts", "\n".join(lines) + "\n")
        from vfio_isolate import cpuset
        cpuset.reset_cgroup_cache()

    # -- helpers ---------------------------------------------------------------------
    def mkcg(self, name: str, cpus: str = "0-7", mems: str = "0") -> Path:
        """Create a child cgroup under the cgroup2 mount, with the files the kernel creates."""
        if self.cgroup_mount is None:
            raise RuntimeError(f"layout {self.layout!r} has no cgroup2 mount")
        d = self.root / self.cgroup_mount.lstrip("/") / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "cgroup.controllers").write_text(CONTROLLERS + "\n")
        (d / "cgroup.subtree_control").write_text("\n")
        (d / "cgroup.procs").write_text("")
        (d / "cpuset.cpus").write_text("\n")
        (d / "cpuset.mems").write_text("\n")
        (d / "cpuset.cpus.effective").write_text(cpus + "\n")
        (d / "cpuset.mems.effective").write_text(mems + "\n")
        return d

    def read(self, relpath: str) -> str:
        return (self.root / relpath.lstrip("/")).read_text()


@pytest.fixture
def fake_host(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(fsroot, "ROOT", str(root))
    # nodeset.py memoizes its sysfs reads in function attributes; clear them
    from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet
    funcs = [CPUNodeSet.present_cpus, CPUNodeSet.possible_cpus,
             NUMANodeSet.online_nodes, NUMANodeSet.possible_nodes]

    def reset():
        for f in funcs:
            f.value = None

    reset()
    host = FakeHost(root)
    yield host
    reset()
    from vfio_isolate import cpuset
    cpuset.reset_cgroup_cache()
