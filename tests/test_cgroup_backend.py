import importlib
import sys

import pytest

from vfio_isolate import cpuset
from vfio_isolate.cpuset import CPUSet, HostUnsupportedError, cgroup_root
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet


def test_pure_v2(fake_host):
    assert cgroup_root() == str(fake_host.root) + "/sys/fs/cgroup"


def test_nonstandard_mount(fake_host):
    fake_host.set_layout("v2-nonstandard")
    assert cgroup_root() == str(fake_host.root) + "/mnt/cg2"


def test_hybrid_rejected(fake_host):
    fake_host.set_layout("hybrid")
    with pytest.raises(HostUnsupportedError, match="bound to a cgroup v1"):
        cgroup_root()


def test_v1_only_rejected(fake_host):
    fake_host.set_layout("v1")
    with pytest.raises(HostUnsupportedError, match="bound to a cgroup v1"):
        cgroup_root()


@pytest.mark.parametrize("opts", ["rw,name=cpuset", "rw,cpuset_v2_mode"])
def test_v1_lookalike_options_not_cpuset(fake_host, opts):
    fake_host.set_layout("v2")
    with open(fake_host.root / "proc/self/mounts", "a") as f:
        f.write(f"cgroup /sys/fs/cgroup/other cgroup {opts} 0 0\n")
    assert cgroup_root() == str(fake_host.root) + "/sys/fs/cgroup"


def test_prefers_standard_mount(fake_host):
    fake_host.set_layout("v2")
    d = fake_host.root / "mnt/cg2"
    d.mkdir(parents=True)
    (d / "cgroup.controllers").write_text("cpuset cpu\n")
    mounts = fake_host.root / "proc/self/mounts"
    mounts.write_text("cgroup2 /mnt/cg2 cgroup2 rw 0 0\n" + mounts.read_text())
    assert cgroup_root() == str(fake_host.root) + "/sys/fs/cgroup"


def test_none(fake_host):
    fake_host.set_layout("none")
    with pytest.raises(HostUnsupportedError, match="cgroup v2 not found"):
        cgroup_root()


def test_no_cpuset(fake_host):
    fake_host.set_layout("no-cpuset")
    with pytest.raises(HostUnsupportedError, match="cpuset controller not available"):
        cgroup_root()


@pytest.mark.parametrize("layout", ["hybrid", "v1", "none", "no-cpuset"])
def test_messages_mention_05(fake_host, layout):
    fake_host.set_layout(layout)
    with pytest.raises(HostUnsupportedError, match=r"0\.5"):
        cgroup_root()


def test_cache_reset(fake_host):
    assert cgroup_root().endswith("/sys/fs/cgroup")
    fake_host.set_layout("v2-nonstandard")  # resets the cache
    assert cgroup_root().endswith("/mnt/cg2")


def test_octal_escape_mountpoint(fake_host):
    fake_host.set_layout("none")
    d = fake_host.root / "mnt/my cg"
    d.mkdir(parents=True)
    (d / "cgroup.controllers").write_text("cpuset cpu\n")
    with open(fake_host.root / "proc/self/mounts", "a") as f:
        f.write("cgroup2 /mnt/my\\040cg cgroup2 rw 0 0\n")
    assert cgroup_root() == str(fake_host.root) + "/mnt/my cg"


@pytest.mark.parametrize("mod", ["vfio_isolate.cpuset", "vfio_isolate.cli"])
def test_import_without_cgroups(fake_host, mod, monkeypatch):
    fake_host.set_layout("none")
    # monkeypatch restores the original module objects afterwards
    import vfio_isolate
    for m in ("vfio_isolate.cpuset", "vfio_isolate.cli"):
        monkeypatch.delitem(sys.modules, m, raising=False)
        # importing also rebinds the submodule attribute on the package; restore it too
        if hasattr(vfio_isolate, m.split(".")[1]):
            monkeypatch.setattr(vfio_isolate, m.split(".")[1], sys.modules.get(m) or getattr(vfio_isolate, m.split(".")[1]))
    importlib.import_module(mod)


def test_cpuset_roundtrip(fake_host):
    fake_host.mkcg("child")
    cs = CPUSet("child")
    assert cs.get_cpus().to_list_form() == "0-7"
    assert cs.get_mems().to_list_form() == "0"
    cs.set_cpus(CPUNodeSet("2-3"))
    cs.set_mems(NUMANodeSet("0"))
    assert fake_host.read("sys/fs/cgroup/child/cpuset.cpus").strip() == "2-3"
    assert fake_host.read("sys/fs/cgroup/child/cpuset.mems").strip() == "0"


def test_pids_and_add_pid(fake_host):
    fake_host.mkcg("child")
    cs = CPUSet("child")
    assert list(cs.pids()) == []
    assert cs.add_pid(1234, silent=True)
    assert fake_host.read("sys/fs/cgroup/child/cgroup.procs") == "1234"
    assert list(cs.pids()) == [1234]
