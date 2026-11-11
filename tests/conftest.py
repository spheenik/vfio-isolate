import errno
import os
import shutil
from pathlib import Path
from typing import Optional

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

    def __init__(self, root: Path, monkeypatch=None, num_cpus: int = NUM_CPUS,
                 governors: str = "performance powersave schedutil"):
        self.root = root
        self.num_cpus = num_cpus
        self.governors = governors
        self._monkeypatch = monkeypatch
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
        last = self.num_cpus - 1
        for n in range(self.num_cpus):
            (self.root / cpu / f"cpu{n}").mkdir(parents=True, exist_ok=True)
            self._write(f"{cpu}/cpu{n}/cpufreq/scaling_governor", "powersave\n")
            self._write(f"{cpu}/cpu{n}/cpufreq/scaling_available_governors",
                        self.governors + "\n")
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
        last = self.num_cpus - 1
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
    def mkcg(self, name: str, cpus: Optional[str] = "0-7", mems: Optional[str] = "0",
             cpuset_files: bool = True) -> Path:
        """Create a child cgroup under the cgroup2 mount, with the files the kernel creates.

        cpus/mems are the effective values; None inherits the parent's effective values.
        The configured cpuset.cpus/cpuset.mems files always start empty ("\\n").
        cpuset_files=False creates the child as the kernel does when the parent lacks cpuset
        in subtree_control: no cpuset.* files (call lazy_cpuset_files() so that enabling the
        controller in the parent creates them)."""
        if self.cgroup_mount is None:
            raise RuntimeError(f"layout {self.layout!r} has no cgroup2 mount")
        d = self.root / self.cgroup_mount.lstrip("/") / name
        d.mkdir(parents=True, exist_ok=True)
        if cpus is None:
            cpus = (d.parent / "cpuset.cpus.effective").read_text().strip()
        if mems is None:
            mems = (d.parent / "cpuset.mems.effective").read_text().strip()
        self._populate_child(d, cpus, mems, cpuset_files)
        if not cpuset_files:  # patch_cgroup_fs may have populated them on mkdir
            for f in d.glob("cpuset.*"):
                f.unlink()
        return d

    def lazy_cpuset_files(self):
        """Opt in: opening a cgroup.subtree_control for writing creates the cpuset.* files in
        child cgroups that lack them, like +cpuset does in the kernel (tool code only)."""
        from vfio_isolate import cpuset
        host = self

        def fake_open(path, mode="r", *a, **kw):
            path = os.fspath(path)
            if "w" in mode and path.endswith("/cgroup.subtree_control"):
                for child in Path(path).parent.iterdir():
                    if child.is_dir() and not (child / "cpuset.cpus").exists():
                        parent_eff = child.parent / "cpuset.cpus.effective"
                        host._populate_child(child, parent_eff.read_text().strip(),
                                             (child.parent / "cpuset.mems.effective").read_text().strip())
            return open(path, mode, *a, **kw)

        self._monkeypatch.setattr(cpuset, "open", fake_open, raising=False)

    @staticmethod
    def _populate_child(d: Path, cpus: str, mems: str, cpuset_files: bool = True):
        (d / "cgroup.controllers").write_text(CONTROLLERS + "\n")
        (d / "cgroup.subtree_control").write_text("\n")
        (d / "cgroup.procs").write_text("")
        if not cpuset_files:
            return
        (d / "cpuset.cpus").write_text("\n")
        (d / "cpuset.mems").write_text("\n")
        (d / "cpuset.cpus.partition").write_text("member\n")
        (d / "cpuset.cpus.effective").write_text(cpus + "\n")
        (d / "cpuset.mems.effective").write_text(mems + "\n")

    def add_irq(self, number: int, affinity: str = "0-7"):
        """Create /proc/irq/<number>/smp_affinity_list (irq-affinity iterates /proc/irq)."""
        self._write(f"proc/irq/{number}/smp_affinity_list", affinity + "\n")

    def patch_cgroup_fs(self):
        """Opt in: os.mkdir/os.rmdir below the cgroup2 mount behave like cgroupfs.

        mkdir populates the control files the kernel creates; rmdir removes the
        directory together with its files (and fails with ENOTEMPTY if it has children).
        """
        mount = str(self.root / self.cgroup_mount.lstrip("/"))
        real_mkdir, real_rmdir = os.mkdir, os.rmdir

        def inside(path):
            path = os.fspath(path)
            return path.startswith(mount + "/")

        def mkdir(path, *args, **kwargs):
            real_mkdir(path, *args, **kwargs)
            if inside(path):
                d = Path(path)
                parent = d.parent
                cpus = (parent / "cpuset.cpus.effective").read_text().strip()
                mems = (parent / "cpuset.mems.effective").read_text().strip()
                self._populate_child(d, cpus, mems)

        def rmdir(path, *args, **kwargs):
            if inside(path):
                entries = list(os.scandir(path))
                if any(e.is_dir(follow_symlinks=False) for e in entries):
                    raise OSError(errno.EBUSY, os.strerror(errno.EBUSY), os.fspath(path))
                for e in entries:
                    os.unlink(e.path)
            real_rmdir(path, *args, **kwargs)

        self._monkeypatch.setattr(os, "mkdir", mkdir)
        self._monkeypatch.setattr(os, "rmdir", rmdir)

    def read(self, relpath: str) -> str:
        return (self.root / relpath.lstrip("/")).read_text()

    def enable_systemd(self, units=None, supports_partition=True) -> "FakeSystemd":
        """Opt in: pretend systemd is PID 1 and replace systemd._run with a fake systemctl.

        units: {unit name: ControlGroup path}; the cgroup directories are created if missing.
        The returned FakeSystemd (also self.systemd) keeps the unit table and records calls.
        """
        (self.root / "run/systemd/system").mkdir(parents=True, exist_ok=True)
        from vfio_isolate import systemd
        fake = FakeSystemd(self, supports_partition)
        for unit, cg in (units or {}).items():
            fake.add_unit(unit, cg)
        self._monkeypatch.setattr(systemd, "_run", fake.run)
        systemd.reset_cache()
        self.systemd = fake
        return fake


def _nl(value: str) -> str:
    return (value + "\n") if value else "\n"


class FakeSystemd:
    """Fake `systemctl` for the subset vfio_isolate uses (show, set-property --runtime).

    units: unit name -> {"ControlGroup": path, "AllowedCPUs": str, "AllowedMemoryNodes": str,
    "CPUSetPartition": str}; list values are held comma separated (as in cgroupfs) and
    printed space separated by `show` (as real systemd does). set-property mirrors the
    properties into the fake cgroup tree. calls: every systemctl invocation (argv lists
    without "systemctl"); set_calls: just the set-property ones.
    """

    KNOWN = ("ControlGroup", "AllowedCPUs", "AllowedMemoryNodes", "CPUSetPartition", "Delegate")
    PARTITION_INVALID = "isolated invalid (Invalid cpu list in cpuset.cpus.exclusive)"

    def __init__(self, host: FakeHost, supports_partition=True):
        self.host = host
        self.supports_partition = supports_partition
        self.units = {}
        self.calls = []

    @property
    def set_calls(self):
        return [c for c in self.calls if c and c[0] == "set-property"]

    def known(self):
        return [p for p in self.KNOWN if p != "CPUSetPartition" or self.supports_partition]

    def add_unit(self, unit: str, cgroup: str, **props):
        if self.host.cgroup_mount is not None:
            d = self.host.root / self.host.cgroup_mount.lstrip("/") / cgroup.strip("/")
            if not d.exists():
                self.host.mkcg(cgroup.strip("/"))
            part = d / "cpuset.cpus.partition"
            if not part.exists():
                part.write_text("member\n")
        self.units[unit] = {"ControlGroup": cgroup, "AllowedCPUs": "", "AllowedMemoryNodes": "",
                            "CPUSetPartition": "", "Delegate": "no"}
        self.units[unit].update(props)

    def cgroup_dir(self, unit: str) -> Path:
        cg = self.units[unit]["ControlGroup"].strip("/")
        return self.host.root / self.host.cgroup_mount.lstrip("/") / cg

    # -- the fake systemctl ----------------------------------------------------------
    def run(self, args) -> str:
        from vfio_isolate.systemd import SystemctlError
        args = list(args)
        self.calls.append(list(args))
        if "--" in args:  # end of options: what follows is a unit name, never an option
            args.remove("--")
        if not args:
            raise SystemctlError("systemctl: no command")
        if args[0] == "show":
            return self._show(args[1:])
        if args[0] == "set-property":
            return self._set_property(args[1:])
        raise SystemctlError(f"fake systemctl: unsupported command {args[0]}")

    def _show(self, args):
        props, value_only, unit = [], False, None
        it = iter(args)
        for a in it:
            if a == "-p":
                props.append(next(it))
            elif a == "--value":
                value_only = True
            else:
                unit = a
        known = self.known()
        if not props:
            props = known
        u = self.units.get(unit)
        lines = []
        for p in props:
            if p not in known:
                continue
            v = u[p] if u else ""
            if p in ("AllowedCPUs", "AllowedMemoryNodes"):
                v = v.replace(",", " ")
            lines.append(v if value_only else f"{p}={v}")
        return "".join(l + "\n" for l in lines)

    def _set_property(self, args):
        from vfio_isolate.systemd import SystemctlError
        if not args or args[0] != "--runtime":
            raise SystemctlError("fake systemctl: set-property without --runtime")
        unit, assigns = args[1], args[2:]
        if unit not in self.units:
            raise SystemctlError(f"Unit {unit} not loaded.")
        new = {}
        for a in assigns:
            k, sep, v = a.partition("=")
            if not sep or k not in self.known() or k in ("ControlGroup", "Delegate"):
                raise SystemctlError(f"Unknown assignment: {a}")
            new[k] = ",".join(v.split()) if k.startswith("Allowed") else v
        u = self.units[unit]
        old_partition = (self.cgroup_dir(unit) / "cpuset.cpus.partition").read_text().strip()
        u.update(new)
        d = self.cgroup_dir(unit)
        parent = d.parent
        for prop, f in (("AllowedCPUs", "cpus"), ("AllowedMemoryNodes", "mems")):
            if prop in new:
                (d / f"cpuset.{f}").write_text(_nl(new[prop]))
                eff = new[prop] or (parent / f"cpuset.{f}.effective").read_text().strip()
                (d / f"cpuset.{f}.effective").write_text(eff + "\n")
        if "CPUSetPartition" in new:
            part = new["CPUSetPartition"] or "member"
            if ("AllowedCPUs" in new and not new["AllowedCPUs"] and not new["CPUSetPartition"]
                    and old_partition.startswith("isolated")):
                # probe 3: resetting both leaves the partition invalid instead of member
                part = self.PARTITION_INVALID
            (d / "cpuset.cpus.partition").write_text(part + "\n")
        return ""


@pytest.fixture
def fake_host_factory(tmp_path, monkeypatch):
    """Returns make(num_cpus=NUM_CPUS, governors=...) -> FakeHost; fake_host is make()."""
    from vfio_isolate import privileges
    from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet
    funcs = [CPUNodeSet.present_cpus, CPUNodeSet.possible_cpus,
             NUMANodeSet.online_nodes, NUMANodeSet.possible_nodes]

    def reset():
        # nodeset.py memoizes its sysfs reads in function attributes; clear them
        for f in funcs:
            f.value = None

    def make(**kwargs):
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setattr(fsroot, "ROOT", str(root))
        monkeypatch.setattr(privileges, "require_root", lambda: None)
        reset()
        return FakeHost(root, monkeypatch, **kwargs)

    yield make
    reset()
    from vfio_isolate import cpuset, systemd
    cpuset.reset_cgroup_cache()
    systemd.reset_cache()


@pytest.fixture
def fake_host(fake_host_factory):
    return fake_host_factory()
