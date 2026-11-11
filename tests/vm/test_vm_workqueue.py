"""workqueue-affinity against the guest's real unbound workqueue mask.

Runs the real CLI as root. The starting masks are restored on teardown.
"""
import glob
import os
import time

import pytest

from vfio_isolate import workqueue
from vfio_isolate.cli import main
from vfio_isolate.nodeset import CPUNodeSet

pytestmark = pytest.mark.vm

WQ = "/sys/devices/virtual/workqueue"
CG = "/sys/fs/cgroup"


def rd(path):
    with open(path) as f:
        return f.read()


def requested():
    return workqueue.read_requested()


def effective():
    return CPUNodeSet.from_mask(rd(f"{WQ}/cpumask"))


def online():
    return workqueue.read_online()


def churn(tmp_path):
    """Generate writeback / block I/O so kworker/u* threads exist and run."""
    for i in range(3):
        with open(tmp_path / f"io{i}", "wb") as f:
            f.write(os.urandom(1 << 20))
            f.flush()
            os.fsync(f.fileno())
    os.sync()


def unbound_kworker_cpus():
    result = {}
    for status in glob.glob("/proc/[0-9]*/status"):
        try:
            text = rd(status)
        except OSError:
            continue
        fields = dict(l.split(":", 1) for l in text.splitlines() if ":" in l)
        if fields.get("Name", "").strip().startswith("kworker/u"):
            result[status] = CPUNodeSet(fields["Cpus_allowed_list"].strip())
    return result


@pytest.fixture
def j(tmp_path):
    return str(tmp_path / "journal")


@pytest.fixture
def cleanup():
    fns = []
    yield fns.append
    for fn in reversed(fns):
        try:
            fn()
        except Exception:
            pass


@pytest.fixture
def start(cleanup):
    """The requested mask at the start; written back on teardown."""
    saved = requested()
    cleanup(lambda: workqueue.write_cpumask(saved))
    return saved


def test_mask_restricts_kworkers_and_restore(j, start, tmp_path):
    cpus = sorted(online())
    assert len(cpus) >= 2, "the guest needs at least 2 CPUs"
    gone = CPUNodeSet(set(cpus[len(cpus) // 2:]))
    keep = online().intersection(gone.negation())
    churn(tmp_path)
    assert main(["-u", j, "workqueue-affinity", "mask", f"C{gone.to_list_form()}"]) == 0
    assert effective().intersection(online()) == keep
    churn(tmp_path)
    time.sleep(0.5)
    workers = unbound_kworker_cpus()
    assert workers, "no kworker/u* thread found"
    for status, allowed in workers.items():
        assert allowed.intersection(online()).intersection(gone) == CPUNodeSet(), (status, allowed)
    assert main(["restore", j]) == 0
    assert requested() == start


@pytest.fixture
def partition_cg(cleanup):
    """Create a leaf cgroup for an isolated partition; torn down on teardown."""
    part = f"{CG}/vmtest-wq"
    os.mkdir(part)

    def remove():
        try:
            with open(f"{part}/cpuset.cpus.partition", "w") as f:
                f.write("member")
            with open(f"{part}/cpuset.cpus", "w") as f:
                f.write("\n")
        finally:
            os.rmdir(part)
    cleanup(remove)
    with open(f"{CG}/cgroup.subtree_control", "w") as f:
        f.write("+cpuset")
    return part


def hi_part():
    cpus = sorted(online())
    assert len(cpus) >= 4, "the guest needs at least 4 CPUs"
    return CPUNodeSet(set(cpus[len(cpus) // 2:]))


def test_isolated_partition_is_refused(j, start, partition_cg, capsys):
    iso = hi_part()
    part = partition_cg
    with open(f"{part}/cpuset.cpus", "w") as f:
        f.write(iso.to_list_form())
    with open(f"{part}/cpuset.cpus.partition", "w") as f:
        f.write("isolated")
    assert rd(f"{part}/cpuset.cpus.partition").strip() == "isolated"
    assert workqueue.read_isolated() == iso
    before_eff, before_req = effective(), requested()

    assert main(["-u", j, "workqueue-affinity", "add", f"C{iso.to_list_form()}"]) == 1
    assert "are in isolated cpuset partitions" in capsys.readouterr().err
    assert effective() == before_eff
    assert requested() == before_req


def test_workqueue_before_partition_restores_exactly(j, start, partition_cg):
    iso = hi_part()
    sub = CPUNodeSet({sorted(iso)[-1]})
    before_eff = effective()
    assert main(["-u", j, "workqueue-affinity", "mask", f"C{sub.to_list_form()}",
                 "cpuset-modify", "--cpus", f"C{iso.to_list_form()}", "--partition", "isolated",
                 "/vmtest-wq"]) == 0
    assert rd(f"{partition_cg}/cpuset.cpus.partition").strip() == "isolated"
    assert effective().intersection(iso) == CPUNodeSet()
    assert main(["restore", j]) == 0
    assert requested() == start
    assert effective() == before_eff
