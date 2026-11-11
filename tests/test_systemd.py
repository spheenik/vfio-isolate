import pytest

from vfio_isolate import systemd
from vfio_isolate.action import PreconditionError


def test_detection(fake_host):
    assert not systemd.systemd_running()
    fake_host.enable_systemd()
    assert systemd.systemd_running()


def test_no_systemd_means_no_unit(fake_host):
    assert systemd.unit_for_cgroup("machine.slice") is None


def test_unit_match(fake_host):
    fake_host.enable_systemd({"machine.slice": "/machine.slice"})
    assert systemd.unit_for_cgroup("machine.slice") == "machine.slice"
    assert systemd.unit_for_cgroup("/machine.slice") == "machine.slice"


def test_unit_nested(fake_host):
    fake_host.enable_systemd({"a.slice": "/x.slice/a.slice"})
    assert systemd.unit_for_cgroup("x.slice/a.slice") == "a.slice"


def test_unit_not_loaded(fake_host):
    fake_host.enable_systemd({"machine.slice": "/machine.slice"})
    assert systemd.unit_for_cgroup("other.slice") is None


def test_unit_mismatch(fake_host):
    fake_host.enable_systemd({"machine.slice": "/elsewhere/machine.slice"})
    with pytest.raises(PreconditionError, match="/elsewhere/machine.slice"):
        systemd.unit_for_cgroup("machine.slice")


def test_non_unit_name_does_not_call_systemctl(fake_host):
    fs = fake_host.enable_systemd({"machine.slice": "/machine.slice"})
    assert systemd.unit_for_cgroup("foo") is None
    assert systemd.unit_for_cgroup("foo/bar") is None
    assert fs.calls == []


def test_root_is_not_a_unit(fake_host):
    fs = fake_host.enable_systemd()
    assert systemd.unit_for_cgroup("/") is None
    assert systemd.unit_for_cgroup("") is None
    assert fs.calls == []


def test_show_normalises_space_lists(fake_host):
    fs = fake_host.enable_systemd({"m.slice": "/m.slice"})
    fs.units["m.slice"]["AllowedCPUs"] = "0-1,4,6-7"
    fs.units["m.slice"]["CPUSetPartition"] = "isolated"
    r = systemd.show("m.slice", ["AllowedCPUs", "AllowedMemoryNodes", "CPUSetPartition"])
    assert r == {"AllowedCPUs": "0-1,4,6-7", "AllowedMemoryNodes": "", "CPUSetPartition": "isolated"}
    assert fs.calls[-1] == ["show", "-p", "AllowedCPUs", "-p", "AllowedMemoryNodes",
                            "-p", "CPUSetPartition", "--", "m.slice"]


def test_show_parses_raw_space_output(monkeypatch):
    monkeypatch.setattr(systemd, "_run", lambda a: "AllowedCPUs=0-1 4 6-7\nAllowedMemoryNodes=\nOther=a b\n")
    assert systemd.show("u.slice", ["AllowedCPUs", "AllowedMemoryNodes"]) == {
        "AllowedCPUs": "0-1,4,6-7", "AllowedMemoryNodes": ""}


def test_set_property_single_call(fake_host):
    fs = fake_host.enable_systemd({"m.slice": "/m.slice"})
    systemd.set_property("m.slice", AllowedCPUs="4-7", CPUSetPartition="isolated")
    assert fs.set_calls == [["set-property", "--runtime", "--", "m.slice",
                             "AllowedCPUs=4-7", "CPUSetPartition=isolated"]]
    assert fake_host.read("sys/fs/cgroup/m.slice/cpuset.cpus") == "4-7\n"
    assert fake_host.read("sys/fs/cgroup/m.slice/cpuset.cpus.effective") == "4-7\n"
    assert fake_host.read("sys/fs/cgroup/m.slice/cpuset.cpus.partition") == "isolated\n"


def test_set_property_empty_resets(fake_host):
    fs = fake_host.enable_systemd({"m.slice": "/m.slice"})
    systemd.set_property("m.slice", AllowedCPUs="4-7")
    systemd.set_property("m.slice", AllowedCPUs="")
    assert fs.set_calls[-1] == ["set-property", "--runtime", "--", "m.slice", "AllowedCPUs="]
    assert fake_host.read("sys/fs/cgroup/m.slice/cpuset.cpus") == "\n"
    assert fake_host.read("sys/fs/cgroup/m.slice/cpuset.cpus.effective") == "0-7\n"


def test_set_property_nothing_is_no_call(fake_host):
    fs = fake_host.enable_systemd({"m.slice": "/m.slice"})
    systemd.set_property("m.slice")
    assert fs.calls == []


def test_fake_reproduces_probe3(fake_host):
    fake_host.enable_systemd({"m.slice": "/m.slice"})
    systemd.set_property("m.slice", AllowedCPUs="4-7", CPUSetPartition="isolated")
    systemd.set_property("m.slice", AllowedCPUs="", CPUSetPartition="")
    assert fake_host.read("sys/fs/cgroup/m.slice/cpuset.cpus.partition").startswith("isolated invalid")
    systemd.set_property("m.slice", AllowedCPUs="", CPUSetPartition="member")
    assert fake_host.read("sys/fs/cgroup/m.slice/cpuset.cpus.partition") == "member\n"


def test_set_property_failure_is_reported(fake_host):
    fake_host.enable_systemd()
    with pytest.raises(systemd.SystemctlError, match="not loaded"):
        systemd.set_property("nope.slice", AllowedCPUs="1")


def test_supports(fake_host):
    fs = fake_host.enable_systemd({"system.slice": "/system.slice"})
    assert systemd.supports("CPUSetPartition")
    assert systemd.supports("CPUSetPartition")
    assert len(fs.calls) == 1  # cached
    assert not systemd.supports("NoSuchThing")


def test_supports_missing_partition(fake_host):
    fake_host.enable_systemd({"system.slice": "/system.slice"}, supports_partition=False)
    assert not systemd.supports("CPUSetPartition")
    assert systemd.supports("AllowedCPUs")
