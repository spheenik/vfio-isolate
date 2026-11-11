"""-n/--dry-run against the guest's real kernel: a hook-like chain changes nothing.

Run as root and, where setpriv exists, as an unprivileged user. State is compared before and
after: systemd properties, IRQ affinities, workqueue masks, hugepage pool, CPU governors.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

from vfio_isolate.cli import main

pytestmark = pytest.mark.vm

LOCK = "/run/vfio-isolate.lock"
JOURNAL = "/run/vfio-dryrun-j"


def rd(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError as e:
        return f"<{e.__class__.__name__}>"


def governor_args():
    avail = rd("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors").split()
    if not avail or avail[0].startswith("<"):
        return []
    return ["cpu-governor", avail[0], "C0-1"]


def chain():
    return ["-n", "-u", JOURNAL,
            "cpuset-modify", "--cpus", "C0", "/user.slice",
            "irq-affinity", "mask", "C1",
            "workqueue-affinity", "mask", "C1",
            "hugepages", "2M", "16M",
            *governor_args()]


def state():
    wq = "/sys/devices/virtual/workqueue"
    show = subprocess.run(["systemctl", "show", "-p", "AllowedCPUs", "-p", "CPUSetPartition", "user.slice"],
                          capture_output=True, text=True).stdout
    return {
        "user.slice": show,
        "irq": {p: rd(p) for p in glob.glob("/proc/irq/*/smp_affinity_list")},
        "wq": {n: rd(f"{wq}/{n}") for n in ("cpumask", "cpumask_requested")},
        "pool": rd("/sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages"),
        "governors": {p: rd(p) for p in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor")},
        "cpuset": rd("/sys/fs/cgroup/user.slice/cpuset.cpus"),
    }


def lock_state():
    try:
        st = os.stat(LOCK)
        return (st.st_ino, st.st_mtime_ns)
    except FileNotFoundError:
        return None


@pytest.fixture(autouse=True)
def no_journal():
    # meaningful for the root test; the unprivileged one could not create it in /run anyway
    assert not os.path.exists(JOURNAL)
    yield
    assert not os.path.exists(JOURNAL), "dry run created the journal"


def test_dry_run_as_root_changes_nothing(capsys):
    assert os.path.isdir("/sys/fs/cgroup/user.slice"), "guest has no user.slice"
    before, lock = state(), lock_state()
    assert main(chain()) == 0
    out = capsys.readouterr().out
    assert f"would record undo in {JOURNAL}" in out
    assert "would set unit user.slice (systemd): AllowedCPUs" in out
    assert "would change affinity of" in out
    assert "would set unbound workqueue mask" in out
    assert "would add 16M in 2M pages (8) to the pool" in out
    assert state() == before
    assert lock_state() == lock  # a lock file left by earlier tests must be untouched, none created


def test_dry_run_as_unprivileged_user(request):
    if shutil.which("setpriv") is None:
        pytest.skip("no setpriv in the guest")
    # the repository (an editable install) may sit in a home directory the user cannot enter
    import vfio_isolate
    base = tempfile.mkdtemp(dir="/run")  # pytest's own tmp dirs are 0700
    request.addfinalizer(lambda: shutil.rmtree(base, ignore_errors=True))
    lib = os.path.join(base, "lib")
    shutil.copytree(os.path.dirname(vfio_isolate.__file__), os.path.join(lib, "vfio_isolate"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for d in (base, lib):
        os.chmod(d, 0o755)
    subprocess.run(["chmod", "-R", "a+rX", str(lib)], check=True)
    code = ("import sys; from vfio_isolate.cli import main; sys.exit(main(sys.argv[1:]))")
    r = subprocess.run(["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups",
                        sys.executable, "-c", code, *chain()],
                       capture_output=True, text=True, cwd="/",
                       env={**os.environ, "PYTHONPATH": str(lib), "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would set unit user.slice (systemd): AllowedCPUs" in r.stdout
    # What this test proves is that a non-root preview runs and exits 0 with real output. It
    # does not assert "nothing changed", the lock or the journal: uid 65534 cannot write
    # /run, /sys, /proc or call systemctl set-property anyway, so those checks would pass even
    # if the dry run tried to write. The root test checks them where they mean something.
