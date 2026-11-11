"""cpuset-management scenarios against the guest's real kernel cgroups and real systemd.

Runs the real CLI (`vfio_isolate.cli.main`, fsroot.ROOT = "/") as root. Every test asserts
state read back from /sys/fs/cgroup.
"""
import os
import signal
import subprocess
import time

import pytest

from vfio_isolate.cli import main

pytestmark = pytest.mark.vm

CG = "/sys/fs/cgroup"


def rd(cg, name):
    with open(f"{CG}/{cg.strip('/')}/{name}") as f:
        return f.read()


def eff(cg):
    return rd(cg, "cpuset.cpus.effective").strip()


def sysctl(*args):
    return subprocess.run(["systemctl", *args], check=True, capture_output=True, text=True).stdout


def allowed_cpus(unit):
    return sysctl("show", "-p", "AllowedCPUs", "--value", unit).strip()


@pytest.fixture
def j(tmp_path):
    return str(tmp_path / "journal")


@pytest.fixture
def cleanup():
    """Collect cleanup callables; run them in reverse order, ignoring failures."""
    fns = []
    yield fns.append
    for fn in reversed(fns):
        try:
            fn()
        except Exception:
            pass


def _rmdir(path):
    for _ in range(50):
        try:
            os.rmdir(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.1)
    os.rmdir(path)


@pytest.fixture
def mkcg(cleanup):
    """Create a plain (non-systemd) cgroup below /sys/fs/cgroup; removed on teardown."""
    def make(name, subtree_cpuset=False):
        path = f"{CG}/{name.strip('/')}"
        os.mkdir(path)
        cleanup(lambda: _rmdir(path))
        if subtree_cpuset:
            with open(f"{path}/cgroup.subtree_control", "w") as f:
                f.write("+cpuset")
        return name
    return make


@pytest.fixture
def sleeper(cleanup):
    """Start a sleeping process; killed on teardown (before cgroup removal)."""
    def start():
        p = subprocess.Popen(["sleep", "infinity"])

        def stop():
            p.send_signal(signal.SIGKILL)
            p.wait()
        cleanup(stop)
        return p
    return start


@pytest.fixture
def unit(cleanup):
    """Start a transient service `vmtest-<n>` in vmtest.slice running sleep; returns its name."""
    counter = [0]

    def start(slice_name="vmtest.slice"):
        counter[0] += 1
        name = f"vmtest-{counter[0]}-{os.getpid()}.service"
        subprocess.run(["systemd-run", "--unit", name, f"--slice={slice_name}", "sleep", "infinity"],
                       check=True, capture_output=True)

        def stop():
            subprocess.run(["systemctl", "stop", name], capture_output=True)
        cleanup(stop)
        return name
    return start


@pytest.fixture
def reset_slice(cleanup):
    """On teardown, reset cpuset properties of a unit so a failed test leaves no restriction."""
    def register(unit_name):
        def reset():
            subprocess.run(["systemctl", "set-property", "--runtime", unit_name,
                            "CPUSetPartition=member", "AllowedCPUs="], capture_output=True)
        cleanup(reset)
    return register


def test_direct_inherit_round_trip(j, mkcg):
    """A non-systemd cgroup with empty cpuset.cpus is restored to empty (inherit)."""
    cg = mkcg("vmtest-direct")
    assert rd(cg, "cpuset.cpus") == "\n"
    parent = eff("/")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/vmtest-direct"]) == 0
    assert rd(cg, "cpuset.cpus") == "0-3\n"
    assert eff(cg) == "0-3"
    assert main(["restore", j]) == 0
    assert rd(cg, "cpuset.cpus") == "\n"
    assert eff(cg) == parent
    assert not os.path.exists(j)


def test_systemd_route_survives_reload_and_restore(j, reset_slice):
    """cpuset-modify on system.slice goes through systemd: AllowedCPUs is set, survives
    daemon-reload, and restore resets it."""
    reset_slice("system.slice")
    root_eff = eff("/")
    assert allowed_cpus("system.slice") == ""
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/system.slice"]) == 0
    assert allowed_cpus("system.slice") == "0-3"
    assert eff("system.slice") == "0-3"
    sysctl("daemon-reload")
    assert allowed_cpus("system.slice") == "0-3"
    assert eff("system.slice") == "0-3"
    assert main(["restore", j]) == 0
    assert allowed_cpus("system.slice") == ""
    assert eff("system.slice") == root_eff


def test_direct_create_enables_ancestor_controller(j, mkcg):
    """cpuset-create below a cgroup without the controller enables it in the ancestor."""
    mkcg("vmtest-a")
    assert "cpuset" not in rd("vmtest-a", "cgroup.subtree_control").split()
    path = f"{CG}/vmtest-a/b"
    assert main(["-u", j, "cpuset-create", "--cpus", "C0-1", "/vmtest-a/b"]) == 0
    try:
        assert "cpuset" in rd("vmtest-a", "cgroup.subtree_control").replace("+", "").split()
        assert rd("vmtest-a/b", "cpuset.cpus") == "0-1\n"
        assert eff("vmtest-a/b") == "0-1"
    finally:
        _rmdir(path)


def test_isolated_partition_via_systemd(j, unit, reset_slice):
    """An isolated partition on a slice with unrestricted siblings: valid, siblings lose the
    CPUs, and restore gives member and the CPUs back."""
    reset_slice("vmtest.slice")
    unit()
    root_eff = eff("/")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated",
                 "/vmtest.slice"]) == 0
    assert rd("vmtest.slice", "cpuset.cpus.partition").strip() == "isolated"
    assert eff("vmtest.slice") == "4-7"
    assert eff("system.slice") == "0-3"
    assert eff("user.slice") == "0-3"
    assert rd("/", "cpuset.cpus.isolated").strip() == "4-7"
    assert main(["restore", j]) == 0
    assert rd("vmtest.slice", "cpuset.cpus.partition").strip() == "member"
    assert rd("/", "cpuset.cpus.isolated").strip() == ""
    assert eff("system.slice") == root_eff
    assert eff("user.slice") == root_eff
    assert eff("vmtest.slice") == root_eff


def test_isolated_partition_direct_and_undo(j, mkcg, sleeper):
    """Same on a non-systemd leaf cgroup that holds a process."""
    mkcg("vmtest-part")
    p = sleeper()
    with open(f"{CG}/vmtest-part/cgroup.procs", "w") as f:
        f.write(str(p.pid))
    root_eff = eff("/")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated",
                 "/vmtest-part"]) == 0
    assert rd("vmtest-part", "cpuset.cpus.partition").strip() == "isolated"
    assert eff("vmtest-part") == "4-7"
    assert eff("system.slice") == "0-3"
    assert rd("/", "cpuset.cpus.isolated").strip() == "4-7"
    assert main(["restore", j]) == 0
    assert rd("vmtest-part", "cpuset.cpus.partition").strip() == "member"
    assert rd("vmtest-part", "cpuset.cpus") == "\n"
    assert eff("system.slice") == root_eff


def test_partition_invalid_reported(j, mkcg, capsys):
    """The kernel refuses a partition whose CPUs another partition already owns: the tool
    exits 1, and restore leaves the cgroup a valid member."""
    mkcg("vmtest-p1")
    mkcg("vmtest-p2")
    assert main(["cpuset-modify", "--cpus", "C4-5", "--partition", "isolated", "/vmtest-p1"]) == 0
    try:
        capsys.readouterr()
        rc = main(["-u", j, "cpuset-modify", "--cpus", "C4-5", "--partition", "isolated",
                   "/vmtest-p2"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "vfio-isolate: partition invalid:" in err
        assert "Traceback" not in err
        assert rd("vmtest-p2", "cpuset.cpus.partition").startswith("isolated invalid")
        assert main(["restore", j]) == 0
        assert rd("vmtest-p2", "cpuset.cpus.partition").strip() == "member"
        assert rd("vmtest-p2", "cpuset.cpus") == "\n"
    finally:
        main(["cpuset-modify", "--partition", "member", "/vmtest-p1"])


def test_modify_below_ancestor_without_cpuset(j, mkcg, cleanup):
    """cpuset-modify below a cgroup lacking cpuset in subtree_control: the child has no cpuset
    files yet, the tool enables the controller in the ancestors, writes the value, and the undo
    (recorded as empty) round-trips."""
    mkcg("vmtest-x")
    assert "cpuset" not in rd("vmtest-x", "cgroup.subtree_control").split()
    path = f"{CG}/vmtest-x/y"
    os.mkdir(path)
    cleanup(lambda: _rmdir(path))
    assert not os.path.exists(f"{path}/cpuset.cpus")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/vmtest-x/y"]) == 0
    assert "cpuset" in rd("vmtest-x", "cgroup.subtree_control").replace("+", "").split()
    assert rd("vmtest-x/y", "cpuset.cpus") == "0-3\n"
    assert eff("vmtest-x/y") == "0-3"
    assert main(["restore", j]) == 0
    assert rd("vmtest-x/y", "cpuset.cpus") == "\n"


def test_create_without_cpus_inherits(mkcg, cleanup):
    """cpuset-create without --cpus leaves cpuset.cpus empty; the effective CPUs are the parent's."""
    path = f"{CG}/vmtest-inh"
    assert main(["cpuset-create", "/vmtest-inh"]) == 0
    cleanup(lambda: _rmdir(path))
    assert rd("vmtest-inh", "cpuset.cpus") == "\n"
    assert eff("vmtest-inh") == eff("/")


def test_partition_only_on_unit_with_allowed_cpus(j, unit, reset_slice):
    """--partition without --cpus is accepted when the unit already has AllowedCPUs; undo
    (CPUSetPartition=member alone) gives a valid member again."""
    reset_slice("vmtest.slice")
    unit()
    sysctl("set-property", "--runtime", "vmtest.slice", "AllowedCPUs=4-7")
    assert main(["-u", j, "cpuset-modify", "--partition", "isolated", "/vmtest.slice"]) == 0
    assert rd("vmtest.slice", "cpuset.cpus.partition").strip() == "isolated"
    assert eff("vmtest.slice") == "4-7"
    assert main(["restore", j]) == 0
    assert rd("vmtest.slice", "cpuset.cpus.partition").strip() == "member"
