import subprocess

import pytest

pytestmark = pytest.mark.vm


def test_pid1_is_systemd():
    with open("/proc/1/comm") as f:
        assert f.read().strip() == "systemd"


def test_cgroup2_has_cpuset():
    with open("/sys/fs/cgroup/cgroup.controllers") as f:
        assert "cpuset" in f.read().split()


def test_systemctl_show_allowed_cpus():
    out = subprocess.run(["systemctl", "show", "-p", "AllowedCPUs", "system.slice"],
                         check=True, capture_output=True, text=True).stdout
    assert out.startswith("AllowedCPUs=")
