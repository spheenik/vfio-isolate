from vfio_isolate import fsroot
from vfio_isolate.cpu import CPUS
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet


def test_path_default_root():
    assert fsroot.path("/sys/devices", "cpu") == "/sys/devices/cpu"


def test_path_strips_leading_slashes(monkeypatch):
    monkeypatch.setattr(fsroot, "ROOT", "/fake")
    assert fsroot.path("/sys", "/devices", "cpu0") == "/fake/sys/devices/cpu0"
    assert fsroot.path("sys/x") == "/fake/sys/x"
    assert fsroot.path("/sys") == "/fake/sys"


def test_path_reads_root_per_call(monkeypatch):
    monkeypatch.setattr(fsroot, "ROOT", "/a")
    first = fsroot.path("x")
    monkeypatch.setattr(fsroot, "ROOT", "/b/")
    assert (first, fsroot.path("x")) == ("/a/x", "/b/x")


def test_cpu_nodesets_from_fake_host(fake_host):
    assert CPUNodeSet.present_cpus().to_list_form() == "0-7"
    assert CPUNodeSet.possible_cpus().to_list_form() == "0-7"
    assert CPUNodeSet({3}).is_valid()
    assert not CPUNodeSet({9}).is_valid()
    assert sorted(c.number for c in CPUS.online()) == list(range(8))


def test_numa_nodeset_from_fake_host(fake_host):
    assert NUMANodeSet.online_nodes().to_list_form() == "0"
    assert NUMANodeSet({0}).get_cpu_nodeset().to_list_form() == "0-7"


def test_layouts_and_mkcg(fake_host):
    assert "cgroup2 /sys/fs/cgroup cgroup2" in fake_host.read("proc/self/mounts")
    cg = fake_host.mkcg("child")
    assert (cg / "cpuset.cpus").exists()
    fake_host.set_layout("v2-nonstandard")
    assert "/mnt/cg2" in fake_host.read("proc/self/mounts")
    fake_host.mkcg("child")
    fake_host.set_layout("no-cpuset")
    assert "cpuset" not in fake_host.read("sys/fs/cgroup/cgroup.controllers")
    for name in ("hybrid", "v1", "none"):
        fake_host.set_layout(name)
