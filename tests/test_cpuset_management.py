"""Scenario tests for openspec/changes/cgroup2-cpuset/specs/cpuset-management/spec.md.

Docstrings say how each scenario is covered: "fake-only" (the fake tree and fake systemctl
prove only the files written and the systemctl arguments, not what a real kernel/systemd
does) or "also VM-verified: tests/vm/<file>::<test>" (checked against the real kernel and systemd).
"""
import os

import pytest

from vfio_isolate.action.cpuset_modify import CPUSetModify
from vfio_isolate.action.cpuset_delete import CPUSetDelete
from vfio_isolate.cli import main
from vfio_isolate.cpuset import CPUSet
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet

CG = "sys/fs/cgroup"


@pytest.fixture
def host(fake_host):
    fake_host.patch_cgroup_fs()
    return fake_host


@pytest.fixture
def j(tmp_path):
    return str(tmp_path / "j")


@pytest.fixture
def writes(monkeypatch):
    """Record every (cgroup name, file) the tool opens for writing through CPUSet.open."""
    log = []
    orig = CPUSet.open

    def rec(self, file, mode="r"):
        if mode != "r":
            log.append((self.name(), file))
        return orig(self, file, mode)

    monkeypatch.setattr(CPUSet, "open", rec)
    return log


@pytest.fixture
def procs(monkeypatch):
    """Make CPUSet.add_pid behave like cgroupfs: move the PID between cgroup.procs files."""
    def move(self, pid, silent=False, report=True):
        from vfio_isolate.cpuset import cgroup_root
        for dp, _, fns in os.walk(cgroup_root()):
            if "cgroup.procs" in fns:
                p = os.path.join(dp, "cgroup.procs")
                with open(p) as f:
                    ids = [l.strip() for l in f if l.strip()]
                if str(pid) in ids:
                    ids.remove(str(pid))
                    with open(p, "w") as f:
                        f.write("".join(i + "\n" for i in ids))
        with open(os.path.join(cgroup_root(), *self.path, "cgroup.procs"), "a") as f:
            f.write(f"{pid}\n")
        return True

    monkeypatch.setattr(CPUSet, "add_pid", move)


def cgdir(host, name):
    return host.root / host.cgroup_mount.lstrip("/") / name.strip("/")


def rd(host, name, file):
    return (cgdir(host, name) / file).read_text()


def procs_of(host, name):
    return sorted(int(x) for x in rd(host, name, "cgroup.procs").split())


def snapshot(root):
    snap = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p) as f:
                snap[p] = (f.read(), os.stat(p).st_mtime_ns)
    return snap


@pytest.fixture
def sd(host):
    return host.enable_systemd(units={"machine.slice": "/machine.slice",
                                      "system.slice": "/system.slice"})


def invalid_after_isolated(monkeypatch):
    """The fake does not validate partitions: make the kernel answer 'invalid' for isolated."""
    orig = CPUSet.get_partition

    def get_partition(self):
        t, reason = orig(self)
        return (t, "Invalid cpu list in cpuset.cpus.exclusive") if t == "isolated" else (t, reason)

    monkeypatch.setattr(CPUSet, "get_partition", get_partition)


# ---------------------------------------------------------------- systemd route

def test_systemd_route_sets_properties(host, sd, writes, capsys):
    """Restricting system.slice on a systemd host. fake-only for the systemctl arguments; also
    VM-verified: tests/vm/test_vm_cpuset.py::test_systemd_route_survives_reload_and_restore."""
    assert main(["cpuset-modify", "--cpus", "C0-3", "/system.slice"]) == 0
    assert sd.set_calls == [["set-property", "--runtime", "--", "system.slice", "AllowedCPUs=0-3"]]
    assert sd.units["system.slice"]["AllowedCPUs"] == "0-3"
    assert rd(host, "system.slice", "cpuset.cpus.effective") == "0-3\n"
    # the tool wrote no cgroup file of the unit itself
    assert writes == []


def test_systemd_route_cpus_mems_in_one_call(host, sd):
    """cpus and mems go into a single set-property call. fake-only."""
    assert main(["cpuset-modify", "--cpus", "C0-3", "--mems", "N0", "/machine.slice"]) == 0
    assert sd.set_calls == [["set-property", "--runtime", "--", "machine.slice",
                             "AllowedCPUs=0-3", "AllowedMemoryNodes=0"]]


def test_systemd_undo_restores_properties(host, sd, j):
    """Undo resets AllowedCPUs on a slice that had none. fake-only; also VM-verified:
    tests/vm/test_vm_cpuset.py::test_systemd_route_survives_reload_and_restore."""
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/system.slice"]) == 0
    assert main(["restore", j]) == 0
    assert sd.units["system.slice"]["AllowedCPUs"] == ""
    assert sd.set_calls[-1] == ["set-property", "--runtime", "--", "system.slice", "AllowedCPUs="]
    assert rd(host, "system.slice", "cpuset.cpus") == "\n"
    assert rd(host, "system.slice", "cpuset.cpus.effective") == "0-7\n"


def test_systemd_undo_restores_previous_values(host, sd, j):
    """Undo of a slice that already had AllowedCPUs restores them (space-separated show
    output is normalised). fake-only."""
    sd.units["system.slice"]["AllowedCPUs"] = "1,5-6"
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/system.slice"]) == 0
    assert main(["restore", j]) == 0
    assert sd.units["system.slice"]["AllowedCPUs"] == "1,5-6"
    assert sd.set_calls[-1][-1] == "AllowedCPUs=1,5-6"


def test_unit_mismatch(host, sd, capsys):
    """Unit path mismatch fails before any change. fake-only."""
    host.mkcg("other.slice")
    sd.units["system.slice"]["ControlGroup"] = "/other.slice"
    assert main(["cpuset-modify", "--cpus", "C0-3", "/system.slice"]) == 1
    err = capsys.readouterr().err
    assert "system.slice" in err and "/other.slice" in err and "/system.slice" in err
    assert sd.set_calls == []


# ---------------------------------------------------------------- direct route

def test_create_enables_controller_on_ancestors(host):
    """Create below a cgroup without the controller (/a/b). fake-only: the fake overwrites
    subtree_control and has no token semantics. Also VM-verified:
    tests/vm/test_vm_cpuset.py::test_direct_create_enables_ancestor_controller."""
    host.mkcg("a")
    assert main(["cpuset-create", "--cpus", "C0-3", "/a/b"]) == 0
    assert rd(host, "/", "cgroup.subtree_control") == "+cpuset"
    assert rd(host, "a", "cgroup.subtree_control") == "+cpuset"
    assert rd(host, "a/b", "cpuset.cpus") == "0-3"
    assert rd(host, "a/b", "cgroup.subtree_control") == "\n"


def test_record_undo_never_writes(host, sd, writes):
    """Reads never write: recording undo on direct and systemd targets, and for delete.
    fake-only."""
    host.mkcg("a")
    host.mkcg("b")
    before = snapshot(host.root)
    p = CPUSetModify.Param(cpuset_name="/a", cpus=CPUNodeSet("0-3"), mems=NUMANodeSet("0"),
                           partition="isolated")
    list(CPUSetModify.record_undo(p))
    list(CPUSetModify.record_undo(CPUSetModify.Param(
        cpuset_name="/system.slice", cpus=CPUNodeSet("0-3"), mems=None, partition="isolated")))
    list(CPUSetDelete.record_undo(CPUSetDelete.Param(cpuset_name="/b")))
    assert snapshot(host.root) == before
    assert writes == []


def test_inheriting_cgroup_round_trip(host, j):
    """An inheriting cgroup (empty cpuset.cpus) is restored to empty, not to effective values.
    fake-only: the fake does not recompute effective CPUs. Also VM-verified: tests/vm/test_vm_cpuset.py::test_direct_inherit_round_trip."""
    host.mkcg("a")
    assert rd(host, "a", "cpuset.cpus") == "\n"
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a"]) == 0
    assert rd(host, "a", "cpuset.cpus") == "0-3"
    assert main(["restore", j]) == 0
    assert rd(host, "a", "cpuset.cpus") == "\n"
    assert rd(host, "a", "cpuset.cpus.effective") == "0-7\n"


def test_create_without_cpus_inherits(host):
    """cpuset-create without --cpus/--mems leaves the files empty. Also VM-verified:
    tests/vm/test_vm_cpuset.py::test_create_without_cpus_inherits."""
    assert main(["cpuset-create", "/a"]) == 0
    assert rd(host, "a", "cpuset.cpus") == "\n"
    assert rd(host, "a", "cpuset.mems") == "\n"


def test_delete_undo_restores_configured_and_partition(host, j):
    """Undo of delete recreates the cgroup with its configured (not effective) values.
    fake-only."""
    cg = host.mkcg("a", cpus="2-3", mems="0")
    (cg / "cpuset.cpus").write_text("2-3\n")
    assert main(["-u", j, "cpuset-delete", "/a"]) == 0
    assert main(["restore", j]) == 0
    assert rd(host, "a", "cpuset.cpus") == "2-3"
    assert rd(host, "a", "cpuset.mems") == "\n"
    assert rd(host, "a", "cpuset.cpus.partition").strip() == "member"


# ---------------------------------------------------------------- partitions

def test_partition_invalid_and_restore(host, j, capsys, monkeypatch):
    """The kernel reports the partition invalid: exit 1 with the reason, restore repairs.
    fake-only (the fake does not validate; the kernel answer is stubbed). Also VM-verified:
    tests/vm/test_vm_cpuset.py::test_partition_invalid_reported."""
    host.mkcg("p")
    invalid_after_isolated(monkeypatch)
    rc = main(["-u", j, "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/p"])
    assert rc == 1
    assert "vfio-isolate: cpuset-modify failed: partition invalid: Invalid cpu list in cpuset.cpus.exclusive" \
        in capsys.readouterr().err
    assert rd(host, "p", "cpuset.cpus.partition") == "isolated"
    assert main(["restore", j]) == 0
    assert rd(host, "p", "cpuset.cpus.partition") == "member"
    assert rd(host, "p", "cpuset.cpus") == "\n"


def test_partition_via_systemd_and_undo(host, sd, j):
    """Isolated partition for the VM slice and its undo go through systemd: forward is one
    call, undo is one call with CPUSetPartition=member plus the previous (empty) cpus; the
    partition ends as member, not invalid (probe 3). fake-only; also VM-verified (including the
    siblings' effective CPUs): tests/vm/test_vm_cpuset.py::test_isolated_partition_via_systemd."""
    assert main(["-u", j, "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated",
                 "/machine.slice"]) == 0
    assert sd.set_calls == [["set-property", "--runtime", "--", "machine.slice",
                             "AllowedCPUs=4-7", "CPUSetPartition=isolated"]]
    assert rd(host, "machine.slice", "cpuset.cpus.partition") == "isolated\n"
    assert main(["restore", j]) == 0
    assert len(sd.set_calls) == 2
    assert sd.set_calls[1] == ["set-property", "--runtime", "--", "machine.slice",
                               "AllowedCPUs=", "CPUSetPartition=member"]
    assert rd(host, "machine.slice", "cpuset.cpus.partition") == "member\n"
    assert rd(host, "machine.slice", "cpuset.cpus") == "\n"


def test_partition_direct_write_order(host, j, writes):
    """Direct path: isolated writes cpus then partition; undo (member) writes partition then
    cpus. fake-only; also VM-verified:
    tests/vm/test_vm_cpuset.py::test_isolated_partition_direct_and_undo."""
    host.mkcg("p")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/p"]) == 0
    assert [f for n, f in writes if n == "/p"] == ["cpuset.cpus", "cpuset.cpus.partition"]
    assert rd(host, "p", "cpuset.cpus.partition") == "isolated"
    del writes[:]
    assert main(["restore", j]) == 0
    assert [f for n, f in writes if n == "/p"] == ["cpuset.cpus.partition", "cpuset.cpus"]
    assert rd(host, "p", "cpuset.cpus.partition") == "member"


def test_partition_unsupported_by_systemd(host, j):
    """CPUSetPartition= unsupported: fail before any change. fake-only."""
    sd = host.enable_systemd(units={"machine.slice": "/machine.slice"}, supports_partition=False)
    assert main(["-u", j, "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated",
                 "/machine.slice"]) == 1
    assert sd.set_calls == []
    assert rd(host, "machine.slice", "cpuset.cpus") == "\n"


def test_partition_unsupported_irrelevant_on_direct_path(host):
    """Unsupported CPUSetPartition only matters for systemd units. fake-only."""
    host.enable_systemd(units={}, supports_partition=False)
    host.mkcg("p")
    assert main(["cpuset-modify", "--partition", "member", "/p"]) == 0


# ---------------------------------------------------------------- move-tasks

def test_move_tasks_undo_moves_back_only_moved(host, procs, j):
    """Pre-existing task stays: PID 100 in /a, PID 200 in /b. fake-only (the fake emulates
    cgroup.procs moves) - VM: not planned."""
    host.mkcg("a")
    host.mkcg("b")
    (cgdir(host, "a") / "cgroup.procs").write_text("100\n")
    (cgdir(host, "b") / "cgroup.procs").write_text("200\n")
    assert main(["-u", j, "move-tasks", "/a", "/b"]) == 0
    assert procs_of(host, "a") == [] and procs_of(host, "b") == [100, 200]
    assert main(["restore", j]) == 0
    assert procs_of(host, "a") == [100]
    assert procs_of(host, "b") == [200]


def test_move_tasks_pids_skips_those_not_in_source(host, procs):
    """With pids set, PIDs that exited or moved elsewhere are skipped silently. fake-only."""
    from vfio_isolate.action.move_tasks import MoveTasks
    host.mkcg("a")
    host.mkcg("b")
    host.mkcg("c")
    (cgdir(host, "b") / "cgroup.procs").write_text("100\n")
    (cgdir(host, "c") / "cgroup.procs").write_text("300\n")
    MoveTasks.execute(MoveTasks.Param(cpuset_from="/b", cpuset_to="/a", pids=[100, 300, 400]))
    assert procs_of(host, "a") == [100]
    assert procs_of(host, "c") == [300]


# ---------------------------------------------------------------- structural rejections

def test_delete_slice_rejected(host, sd, capsys):
    """Deleting a systemd slice is rejected before any change. fake-only."""
    assert main(["cpuset-delete", "/system.slice"]) == 1
    assert "managed by systemd" in capsys.readouterr().err
    assert cgdir(host, "system.slice").exists()
    assert sd.set_calls == []


def test_create_unit_rejected(host, sd, capsys):
    """Creating (over) a unit's cgroup is rejected. fake-only."""
    assert main(["cpuset-create", "/system.slice"]) == 1
    assert "managed by systemd" in capsys.readouterr().err


def test_create_below_non_delegated_slice_rejected(host, sd, capsys):
    """Creating below a Delegate=no slice is rejected before any change. fake-only."""
    assert main(["cpuset-create", "/machine.slice/foo"]) == 1
    assert "managed by systemd" in capsys.readouterr().err
    assert not cgdir(host, "machine.slice/foo").exists()


def test_create_below_delegated_slice_allowed(host, sd):
    """Delegate=yes allows creating below the slice. fake-only."""
    sd.add_unit("user.slice", "/user.slice", Delegate="yes")
    assert main(["cpuset-create", "--cpus", "C0-1", "/user.slice/foo"]) == 0
    assert rd(host, "user.slice/foo", "cpuset.cpus") == "0-1"


@pytest.mark.parametrize("cmd", [["cpuset-modify", "--cpus", "C0-3"], ["cpuset-create"],
                                 ["cpuset-delete"]])
def test_root_rejected(host, cmd, capsys):
    """modify/create/delete are rejected for the root cgroup. fake-only."""
    before = snapshot(host.root)
    assert main(cmd + ["/"]) == 1
    assert "root" in capsys.readouterr().err
    assert snapshot(host.root) == before


# ---------------------------------------------------- controller not enabled on the path

def test_modify_below_ancestor_without_cpuset(host, j):
    """cpuset-modify on a cgroup whose parent lacks cpuset in subtree_control (so the child has
    no cpuset.* files): reading for the undo does not fail or write, the ancestors get the
    controller, the value is written, undo is recorded as empty and restore round-trips.
    Also VM-verified: tests/vm/test_vm_cpuset.py::test_modify_below_ancestor_without_cpuset."""
    host.lazy_cpuset_files()
    host.mkcg("a")
    host.mkcg("a/b", cpuset_files=False)
    assert not cgdir(host, "a/b/cpuset.cpus").exists()
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "--mems", "N0", "/a/b"]) == 0
    assert rd(host, "a", "cgroup.subtree_control") == "+cpuset"
    assert rd(host, "a/b", "cpuset.cpus") == "0-3"
    assert main(["restore", j]) == 0
    assert rd(host, "a/b", "cpuset.cpus") == "\n"
    assert rd(host, "a/b", "cpuset.mems") == "\n"


def test_record_undo_without_cpuset_files_never_writes(host, writes):
    """Recording undo for modify and delete on a cgroup without cpuset files reads as empty /
    member and writes nothing. fake-only."""
    from vfio_isolate.action.cpuset_delete import CPUSetDelete
    host.mkcg("a")
    host.mkcg("a/b", cpuset_files=False)
    cpus, mems = CPUNodeSet("0-1"), NUMANodeSet("0")
    mod = list(CPUSetModify.record_undo(CPUSetModify.Param("/a/b", cpus, mems, "isolated")))
    q = mod[0].params
    assert (q.cpus, q.mems, q.partition) == (CPUNodeSet(""), NUMANodeSet(""), "member")
    undo = list(CPUSetDelete.record_undo(CPUSetDelete.Param("/a/b")))
    assert undo[1].params.partition == "member"
    assert writes == []


def test_delete_below_ancestor_without_cpuset(host, j):
    """cpuset-delete on a cgroup without cpuset files works and its undo recreates it. fake-only."""
    host.lazy_cpuset_files()
    host.mkcg("a")
    host.mkcg("a/b", cpuset_files=False)
    assert main(["-u", j, "cpuset-delete", "/a/b"]) == 0
    assert not cgdir(host, "a/b").exists()
    assert main(["restore", j]) == 0
    assert cgdir(host, "a/b").exists()
    assert rd(host, "a/b", "cpuset.cpus") == "\n"


# ------------------------------------------------------------ partition read-back / systemd

def test_partition_type_mismatch_direct(host, monkeypatch, capsys):
    """The kernel reports a valid partition of another type than requested: exit 1. fake-only."""
    host.mkcg("p")
    monkeypatch.setattr(CPUSet, "get_partition", lambda self: ("member", None))
    assert main(["cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/p"]) == 1
    assert "kernel reports member, requested isolated" in capsys.readouterr().err


def test_partition_type_mismatch_systemd(host, sd, monkeypatch, capsys):
    """Same on the systemd route. fake-only."""
    monkeypatch.setattr(CPUSet, "get_partition", lambda self: ("member", None))
    assert main(["cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/machine.slice"]) == 1
    assert "kernel reports member, requested isolated" in capsys.readouterr().err


def test_partition_without_cpus_needs_allowed_cpus(host, sd, capsys):
    """--partition root/isolated without --cpus on a unit with no AllowedCPUs is refused before
    any change; with AllowedCPUs already set it goes through. fake-only."""
    assert main(["cpuset-modify", "--partition", "isolated", "/machine.slice"]) == 1
    assert "--cpus is required" in capsys.readouterr().err
    assert sd.set_calls == []
    sd.units["machine.slice"]["AllowedCPUs"] = "4-7"
    assert main(["cpuset-modify", "--partition", "isolated", "/machine.slice"]) == 0
    assert sd.set_calls == [["set-property", "--runtime", "--", "machine.slice",
                             "CPUSetPartition=isolated"]]
    assert main(["cpuset-modify", "--partition", "member", "/system.slice"]) == 0


# ------------------------------------------------------------ cpuset-delete retry / children
class _Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr("vfio_isolate.action.cpuset_delete.time.monotonic", c.monotonic)
    monkeypatch.setattr("vfio_isolate.action.cpuset_delete.time.sleep", c.sleep)
    return c


def _count_moves(monkeypatch):
    moves = []
    orig = CPUSet.add_all_from_cpuset

    def rec(self, other, **kw):
        moves.append(other.name())
        return orig(self, other, **kw)

    monkeypatch.setattr(CPUSet, "add_all_from_cpuset", rec)
    return moves


def test_delete_with_child_cgroup_refused(host, j, capsys, monkeypatch):
    """cpuset-delete refuses a cgroup with children before any task move or journal record. fake-only."""
    host.mkcg("a")
    host.mkcg("a/b")
    moves = _count_moves(monkeypatch)
    assert main(["-u", j, "cpuset-delete", "/a"]) == 1
    assert "/a/b" in capsys.readouterr().err
    assert moves == []
    with open(j) as f:
        assert len(f.read().splitlines()) <= 1  # header only, no record
    assert cgdir(host, "a").exists()


def _patch_rmdir(monkeypatch, errnos):
    """os.rmdir (as used by CPUSet.remove) raises the given errnos in turn, then works."""
    calls = []
    orig = os.rmdir

    def rmdir(path):
        calls.append(path)
        if len(calls) <= len(errnos):
            raise OSError(errnos[len(calls) - 1], os.strerror(errnos[len(calls) - 1]), path)
        return orig(path)

    monkeypatch.setattr("vfio_isolate.cpuset.os.rmdir", rmdir)
    return calls


def test_delete_retries_on_ebusy(host, clock, monkeypatch):
    """EBUSY once: tasks are moved again and the cgroup is removed. fake-only."""
    import errno
    host.mkcg("a")
    moves = _count_moves(monkeypatch)
    calls = _patch_rmdir(monkeypatch, [errno.EBUSY])
    assert main(["cpuset-delete", "/a"]) == 0
    assert len(calls) == 2
    assert moves == ["/a", "/a"]
    assert clock.sleeps == [0.05]
    assert not cgdir(host, "a").exists()


def test_delete_ebusy_forever_fails(host, j, clock, monkeypatch, capsys):
    """EBUSY until the deadline: exit 1, 'still in use', restore hint. fake-only."""
    import errno
    host.mkcg("a")
    _patch_rmdir(monkeypatch, [errno.EBUSY] * 10000)
    assert main(["-u", j, "cpuset-delete", "/a"]) == 1
    err = capsys.readouterr().err
    assert "cpuset-delete failed: cpuset /a is still in use" in err
    assert "restore" in err
    assert clock.now >= 2.0
    assert cgdir(host, "a").exists()


def test_delete_other_errno_not_retried(host, clock, monkeypatch, capsys):
    """A non-EBUSY errno is reported at once, without retry. fake-only."""
    import errno
    host.mkcg("a")
    calls = _patch_rmdir(monkeypatch, [errno.EACCES] * 10)
    assert main(["cpuset-delete", "/a"]) == 1
    assert len(calls) == 1
    assert clock.sleeps == []
    assert "cpuset-delete failed" in capsys.readouterr().err


def test_restore_with_new_child_cgroup_fails_fast(host, j, clock, capsys):
    """Undo of create hits a cgroup that gained a child since: no 2 s retry, child named,
    journal kept with the failed step. fake-only."""
    assert main(["-u", j, "cpuset-create", "/a"]) == 0
    host.mkcg("a/b")
    capsys.readouterr()
    assert main(["restore", j]) == 1
    err = capsys.readouterr().err
    assert "/a/b" in err and "child cgroups" in err
    assert "still in use" not in err
    assert clock.sleeps == []
    assert cgdir(host, "a").exists()
    with open(j) as f:
        assert len(f.read().splitlines()) >= 2  # header + the failed step


def test_delete_retry_counts_unmovable_task_once(host, clock, monkeypatch, capsys):
    """A task whose move fails on every pass is reported once although the move is retried. fake-only."""
    import builtins
    import errno
    host.mkcg("a")
    (cgdir(host, "a") / "cgroup.procs").write_text("900001\n")
    real_open = builtins.open

    def fake_open(path, mode="r", *a, **kw):
        if "w" in mode and str(path).endswith("sys/fs/cgroup/cgroup.procs"):
            raise OSError(errno.ESRCH, "injected")
        return real_open(path, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", fake_open)
    _patch_rmdir(monkeypatch, [errno.EBUSY, errno.EBUSY])
    capsys.readouterr()
    assert main(["cpuset-delete", "/a"]) == 0
    err = capsys.readouterr().err
    assert "1 task exited before it could be moved" in err
    assert clock.sleeps == [0.05, 0.05]
