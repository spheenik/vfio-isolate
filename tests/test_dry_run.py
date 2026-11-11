"""Scenario tests for openspec/changes/dry-run/specs/dry-run/spec.md (fake host only)."""
import json
import os

import pytest

from vfio_isolate import privileges
from vfio_isolate.cli import main


@pytest.fixture
def host(fake_host):
    fake_host.patch_cgroup_fs()
    return fake_host


@pytest.fixture
def j(tmp_path):
    return str(tmp_path / "j")


def snapshot(root):
    snap = {}
    for dp, dns, fns in os.walk(root):
        for n in dns:
            snap[os.path.join(dp, n)] = None
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p) as f:
                snap[p] = (f.read(), os.stat(p).st_mtime_ns)
    return snap


def run(argv, capsys):
    rc = main(argv)
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_preview_hook_line(host, j, capsys):
    host.mkcg("system.slice")
    host.add_irq(41)
    before = snapshot(host.root)
    rc, out, err = run(["-n", "-u", j, "cpuset-modify", "--cpus", "C0-7", "/system.slice",
                        "irq-affinity", "mask", "C0-3"], capsys)
    assert rc == 0, err
    assert f"would record undo in {j}" in out
    assert "would set cpuset /system.slice: cpus (inherit) -> 0-7" in out
    assert "change affinity of 1 of 1 IRQ (mask 0-3)" in out
    assert not os.path.exists(j)
    assert snapshot(host.root) == before
    assert not os.path.exists(host.root / "run/vfio-isolate.lock")


def test_precondition_fails(host, j, capsys):
    before = snapshot(host.root)
    rc, out, err = run(["-n", "-u", j, "cpuset-delete", "/missing"], capsys)
    assert rc == 1
    assert err.startswith("vfio-isolate: dry run: cpuset-delete failed: cpuset /missing does not exist")
    assert "restore" not in err and "remain" not in err
    assert not os.path.exists(j)
    assert snapshot(host.root) == before


def test_precondition_stops_at_first_failure(host, capsys):
    host.mkcg("a")
    rc, out, err = run(["-n", "cpuset-modify", "--cpus", "C0-1", "/a",
                        "cpuset-delete", "/missing", "cpuset-modify", "--cpus", "C0-2", "/a"], capsys)
    assert rc == 1
    assert "would set cpuset /a: cpus (inherit) -> 0-1" in out
    assert "0-2" not in out


def test_create_then_move(host, capsys):
    before = snapshot(host.root)
    rc, out, err = run(["-n", "cpuset-create", "--cpus", "C0-7", "/a", "move-tasks", "/", "/a"], capsys)
    assert rc == 0, err
    assert "would create cpuset /a" in out
    assert "would set cpuset /a (new): cpus 0-7" in out
    assert "would move 0 tasks from / to /a (now)" in out
    assert snapshot(host.root) == before
    assert not (host.root / "sys/fs/cgroup/a").exists()


def test_move_counts_follow_chain(host, capsys):
    (host.root / "sys/fs/cgroup/cgroup.procs").write_text("1\n2\n3\n")
    rc, out, err = run(["-n", "cpuset-create", "/a", "move-tasks", "/", "/a",
                        "move-tasks", "/a", "/"], capsys)
    assert rc == 0, err
    assert "would move 3 tasks from / to /a (now)" in out
    assert "would move 3 tasks from /a to / (after earlier steps)" in out


def test_create_existing_and_delete_then_create(host, capsys):
    host.mkcg("a")
    rc, out, err = run(["-n", "cpuset-create", "/a"], capsys)
    assert rc == 1 and "already exists" in err
    rc, out, err = run(["-n", "cpuset-delete", "/a", "cpuset-create", "/a",
                        "cpuset-delete", "/a"], capsys)
    assert rc == 0, err
    assert "would delete cpuset /a" in out
    rc, out, err = run(["-n", "cpuset-delete", "/a", "move-tasks", "/", "/a"], capsys)
    assert rc == 1 and "cpuset /a does not exist" in err
    host.mkcg("a/b")
    rc, out, err = run(["-n", "cpuset-delete", "/a/b", "cpuset-delete", "/a"], capsys)
    assert rc == 0, err
    rc, out, err = run(["-n", "cpuset-create", "/a/c", "cpuset-delete", "/a/b", "cpuset-delete", "/a"], capsys)
    assert rc == 1 and "child cgroups: /a/c" in err


def test_non_root_preview(host, monkeypatch, capsys):
    def deny():
        raise AssertionError("require_root called in a dry run")
    monkeypatch.setattr(privileges, "require_root", deny)
    host.add_irq(41)
    rc, out, err = run(["-n", "irq-affinity", "mask", "C0-3"], capsys)
    assert rc == 0, err
    assert "change affinity of 1 of 1 IRQ (mask 0-3)" in out
    # a real run is refused, proving the patch is in effect
    monkeypatch.setattr(privileges, "require_root", lambda: (_ for _ in ()).throw(
        privileges.NotRootError("root needed")))
    assert main(["irq-affinity", "mask", "C0-3"]) == 1


def test_unreadable_value_is_unknown(host, monkeypatch, capsys):
    host.mkcg("a")
    from vfio_isolate.cpuset import CPUSet
    orig = CPUSet.open

    def deny(self, file, mode="r"):
        if file == "cpuset.cpus":
            raise PermissionError(13, "Permission denied")
        return orig(self, file, mode)
    monkeypatch.setattr(CPUSet, "open", deny)
    rc, out, err = run(["-n", "cpuset-modify", "--cpus", "C0-1", "/a"], capsys)
    assert rc == 0, err
    assert "cpus unknown (permission denied) -> 0-1" in out


def test_systemd_route_read_only(host, j, capsys):
    sd = host.enable_systemd(units={"machine.slice": "/machine.slice"})
    sd.units["machine.slice"]["AllowedCPUs"] = "0-7"
    before = snapshot(host.root)
    rc, out, err = run(["-n", "-u", j, "cpuset-modify", "--cpus", "C0-3", "--partition", "isolated",
                        "/machine.slice"], capsys)
    assert rc == 0, err
    assert "would set unit machine.slice (systemd): AllowedCPUs 0-7 -> 0-3" in out
    assert "CPUSetPartition member -> isolated" in out
    assert {c[0] for c in sd.calls} == {"show"}
    assert sd.set_calls == []
    assert snapshot(host.root) == before


def test_restore_preview(host, j, capsys):
    host.mkcg("a")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a"]) == 0
    assert main(["-u", j, "cpuset-delete", "/a"]) == 0
    capsys.readouterr()
    before = snapshot(host.root)
    journal_before = open(j).read()
    rc, out, err = run(["-n", "restore", j], capsys)
    assert rc == 0, err
    lines = out.splitlines()
    assert lines[0].startswith(f"would restore {j} (2 records")
    assert lines.index("would create cpuset /a") < len(lines)
    assert any("(new): cpus 0-3" in l for l in lines)   # newest record (the delete) first
    assert lines[-1] == "would set cpuset /a (new): cpus (inherit)"  # older record last
    assert open(j).read() == journal_before
    assert snapshot(host.root) == before


def test_every_action_defines_describe():
    from vfio_isolate.action import ACTIONS
    from vfio_isolate.action.action import Action
    missing = [n for n, c in ACTIONS.items() if "describe" not in vars(c)]
    assert not missing, f"actions without their own describe: {missing}"
    base = Action.__dict__["describe"]
    assert all(c.__dict__["describe"] is not base for c in ACTIONS.values())
    assert not [n for n, c in ACTIONS.items() if "touches" not in vars(c)], "actions without touches"
    # existence and task counts are simulated; values are only marked via touches/reads
    needs_overlay = {n for n, c in ACTIONS.items() if "overlay" in vars(c)}
    assert needs_overlay <= {"cpuset-create", "cpuset-delete", "move-tasks", "cpuset-modify"}


def test_governor_groups_consecutive_cpus(host, capsys):
    (host.root / "sys/devices/system/cpu/cpu3/cpufreq/scaling_governor").write_text("schedutil\n")
    (host.root / "sys/devices/system/cpu/cpu4/cpufreq/scaling_governor").write_text("schedutil\n")
    rc, out, err = run(["-n", "cpu-governor", "performance", "C0-5"], capsys)
    assert rc == 0, err
    assert out.splitlines() == [
        "would set governor of CPUs 0-2: powersave -> performance",
        "would set governor of CPUs 3-4: schedutil -> performance",
        "would set governor of CPU 5: powersave -> performance"]


def test_irq_summary_and_verbose(host, capsys):
    for n in (24, 25, 26):
        host.add_irq(n, "0-7")
    host.add_irq(27, "4-7")
    rc, out, err = run(["-n", "irq-affinity", "mask", "C4-7"], capsys)
    assert rc == 0, err
    assert out.splitlines() == ["would change affinity of 4 of 4 IRQs (mask 4-7)"]
    rc, out, err = run(["-n", "-v", "irq-affinity", "mask", "C4-5"], capsys)
    lines = out.splitlines()
    assert lines[0] == "would change affinity of 4 of 4 IRQs (mask 4-5)"
    assert sorted(lines[1:]) == ["  IRQ 24: 0-7 -> 0-3,6-7", "  IRQ 25: 0-7 -> 0-3,6-7",
                                 "  IRQ 26: 0-7 -> 0-3,6-7", "  IRQ 27: 4-7 -> 6-7"]
    # an IRQ that would not change is not counted
    rc, out, err = run(["-n", "irq-affinity", "add", "C0-7"], capsys)
    assert out.splitlines() == ["would change affinity of 1 of 4 IRQs (add 0-7)"]


def test_irq_unreadable_is_unknown(host, monkeypatch, capsys):
    host.add_irq(24)
    host.add_irq(25)
    from vfio_isolate.irq import IRQ
    orig = IRQ.get_affinity

    def deny(self):
        if self.number == 25:
            raise PermissionError(13, "Permission denied")
        return orig(self)
    monkeypatch.setattr(IRQ, "get_affinity", deny)
    rc, out, err = run(["-n", "irq-affinity", "mask", "C0-1"], capsys)
    assert rc == 0, err
    assert "change affinity of 1 of 2 IRQs (mask 0-1); 1 unknown (permission denied)" in out


def test_hugepages_and_release_form(host, j, capsys):
    host.set_hugepages(2048, 100)
    rc, out, err = run(["-n", "hugepages", "2M", "16G"], capsys)
    assert rc == 0, err
    assert out.strip() == ("would add 16G in 2M pages (8192) to the pool, now 100; "
                           "whether the kernel can supply them shows only in a real run")
    assert host.hugepages(2048) == 100
    assert main(["-u", j, "hugepages", "2M", "4M"]) == 0
    capsys.readouterr()
    rc, out, err = run(["-n", "restore", j], capsys)
    assert rc == 0, err
    assert "would release 4M in 2M pages (2) from the pool, now 102" in out
    assert host.hugepages(2048) == 102


def test_workqueue_preview_and_refusal(host, capsys):
    rc, out, err = run(["-n", "workqueue-affinity", "mask", "C4-7"], capsys)
    assert rc == 0, err
    assert out.strip() == "would set unbound workqueue mask: 0-7 -> 0-3"
    assert host.workqueue_mask() == host.workqueue_mask("cpumask_requested")
    host.set_workqueue("0-7", isolated="4-7")
    rc, out, err = run(["-n", "workqueue-affinity", "mask", "C0"], capsys)
    assert rc == 1
    assert "are in isolated cpuset partitions" in err and "dry run:" in err


def test_drop_caches_compact_memory(host, capsys):
    rc, out, err = run(["-n", "drop-caches", "compact-memory"], capsys)
    assert rc == 0, err
    assert out.splitlines() == [
        "would drop page cache, dentries and inodes (write 3 to /proc/sys/vm/drop_caches)",
        "would compact memory (write 1 to /proc/sys/vm/compact_memory)"]
    assert (host.root / "proc/sys/vm/drop_caches").read_text() == "0"


NOTE = "(precondition checked only in a real run: depends on earlier steps)"


def test_modify_twice_second_is_marked(host, capsys):
    host.mkcg("a")
    rc, out, err = run(["-n", "cpuset-modify", "--cpus", "C0-3", "/a",
                        "cpuset-modify", "--cpus", "C0-1", "--mems", "N0", "/a"], capsys)
    assert rc == 0, err
    lines = out.splitlines()
    assert lines[0] == "would set cpuset /a: cpus (inherit) -> 0-3"
    assert "would set cpuset /a: cpus (after earlier steps) -> 0-1" in lines
    assert "would set cpuset /a: mems (after earlier steps) -> 0" in lines


def test_modify_twice_systemd_no_false_failure(host, capsys):
    sd = host.enable_systemd(units={"machine.slice": "/machine.slice"})
    rc, out, err = run(["-n", "cpuset-modify", "--cpus", "C0-3", "/machine.slice",
                        "cpuset-modify", "--partition", "isolated", "/machine.slice"], capsys)
    # the second step needs AllowedCPUs, which the first one sets: not a failure
    assert rc == 0, err
    assert "CPUSetPartition (after earlier steps) -> isolated" in out
    assert NOTE in out
    assert sd.set_calls == []


def test_partition_then_workqueue_is_not_a_false_pass(host, capsys):
    host.mkcg("a")
    # the partition isolates known CPUs: the real run refuses the workqueue step, so does the preview
    rc, out, err = run(["-n", "cpuset-modify", "--cpus", "C4-7", "--partition", "isolated", "/a",
                        "workqueue-affinity", "mask", "C4-7"], capsys)
    assert rc == 1
    assert err.startswith("vfio-isolate: dry run: workqueue-affinity failed: CPUs 4-7 are in isolated cpuset")
    assert NOTE not in out
    # CPUs not known beforehand: not exactly knowable, so a note instead of a verdict
    rc, out, err = run(["-n", "cpuset-modify", "--partition", "isolated", "/a",
                        "workqueue-affinity", "mask", "C4-7"], capsys)
    assert rc == 0, err
    lines = out.splitlines()
    assert lines[-2] == "would set unbound workqueue mask: (after earlier steps) -> the current mask without 4-7"
    assert lines[-1].strip() == NOTE
    # the other order is checked for real
    rc, out, err = run(["-n", "workqueue-affinity", "mask", "C4-7", "cpuset-modify", "--cpus", "C4-7",
                        "--partition", "isolated", "/a"], capsys)
    assert rc == 0, err
    assert NOTE not in out and "would set unbound workqueue mask: 0-7 -> 0-3" in out


def test_workqueue_twice(host, capsys):
    rc, out, err = run(["-n", "workqueue-affinity", "mask", "C4-7", "workqueue-affinity", "add", "C6"], capsys)
    assert rc == 0, err
    lines = out.splitlines()
    assert lines[0] == "would set unbound workqueue mask: 0-7 -> 0-3"
    assert lines[1] == "would set unbound workqueue mask: (after earlier steps) -> the current mask plus 6"
    assert lines[2].strip() == NOTE


def test_workqueue_refusal_on_stale_state_not_reported(host, capsys):
    # earlier steps decide whether CPUs are isolated: the stale disk state must not fail the step
    host.set_workqueue("0-7", isolated="4-7")
    host.mkcg("a")
    rc, out, err = run(["-n", "cpuset-modify", "--partition", "member", "/a",
                        "workqueue-affinity", "mask", "C0"], capsys)
    assert rc == 0, err
    assert NOTE in out


def test_hugepages_twice(host, capsys):
    host.set_hugepages(2048, 100)
    rc, out, err = run(["-n", "hugepages", "2M", "4M", "hugepages", "2M", "2M"], capsys)
    assert rc == 0, err
    lines = out.splitlines()
    assert "to the pool, now 100;" in lines[0]
    assert "to the pool, now (after earlier steps);" in lines[1]


def test_governor_twice(host, capsys):
    rc, out, err = run(["-n", "cpu-governor", "performance", "C0-1",
                        "cpu-governor", "powersave", "C1-2"], capsys)
    assert rc == 0, err
    assert out.splitlines() == [
        "would set governor of CPUs 0-1: powersave -> performance",
        "would set governor of CPU 1: (after earlier steps) -> powersave",
        "would set governor of CPU 2: powersave -> powersave"]


def test_irq_mask_then_add(host, capsys):
    for n in (24, 25):
        host.add_irq(n, "0-7")
    rc, out, err = run(["-n", "irq-affinity", "mask", "C0-3", "irq-affinity", "add", "C0"], capsys)
    assert rc == 0, err
    assert out.splitlines() == ["would change affinity of 2 of 2 IRQs (mask 0-3)",
                                "would change affinity of 0 of 2 IRQs (add 0); 2 depend on earlier steps"]


def test_restore_records_do_not_merge_and_depend(host, j, capsys):
    for n in (24, 25):
        host.add_irq(n, "0-7")
    assert main(["-u", j, "irq-affinity", "mask", "C0-3"]) == 0
    assert main(["-u", j, "irq-affinity", "mask", "C4-5"]) == 0
    capsys.readouterr()
    before = open(j, "rb").read()
    rc, out, err = run(["restore", "-n", j], capsys)
    assert rc == 0, err
    lines = out.splitlines()
    # one record per IRQ: the records stay separate descriptions, never merged into one summary
    assert lines[1:3] == ["would change affinity of 1 of 1 IRQ (add 4-5)"] * 2
    # the older records touch IRQs an earlier (newer) restore step already changed
    assert lines[3:5] == ["would change affinity of 0 of 1 IRQ (add 0-3); 1 depends on earlier steps"] * 2
    assert open(j, "rb").read() == before


def test_restore_dry_run_forms(host, j, capsys):
    host.mkcg("a")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a"]) == 0
    capsys.readouterr()
    rc1, out1, _ = run(["restore", "-n", j], capsys)
    rc2, out2, _ = run(["-n", "restore", j], capsys)
    assert rc1 == rc2 == 0 and out1 == out2 and "would restore" in out1


def test_recorded_move_applies_overlay(host, j, capsys):
    host.mkcg("a")
    (host.root / "sys/fs/cgroup/a/cgroup.procs").write_text("7\n8\n")
    assert main(["-u", j, "move-tasks", "/a", "/"]) == 0
    capsys.readouterr()
    rc, out, err = run(["-n", "restore", j, "move-tasks", "/", "/a"], capsys)
    assert rc == 0, err
    assert "would move 2 recorded tasks from / to /a" in out
    assert "task count unknown (depends on earlier steps)" in out


def test_unknown_reasons_and_plural(host, monkeypatch, capsys):
    host.mkcg("a")
    (host.root / "sys/fs/cgroup/a/cgroup.procs").write_text("7\n")
    rc, out, err = run(["-n", "cpuset-delete", "/a"], capsys)
    assert "its 1 task moves to /" in out
    from vfio_isolate.cpuset import CPUSet
    orig = CPUSet.pids

    def gone(self):
        raise FileNotFoundError(2, "No such file or directory")
    monkeypatch.setattr(CPUSet, "pids", gone)
    rc, out, err = run(["-n", "cpuset-delete", "/a"], capsys)
    assert "its unknown (does not exist) tasks move" in out
    monkeypatch.setattr(CPUSet, "pids", orig)


def test_modify_missing_cpuset_in_restore_says_so(host, j, capsys):
    host.mkcg("a")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a"]) == 0
    capsys.readouterr()
    import shutil
    shutil.rmtree(host.root / "sys/fs/cgroup/a")
    rc, out, err = run(["-n", "restore", j], capsys)
    assert rc == 0, err
    assert "cpus does not exist -> (inherit)" in out and "(inherit) ->" not in out


def test_undo_file_validated_in_dry_run(host, j, tmp_path, capsys):
    open(j, "wb").write(b"\x80\x04pickle")
    os.chmod(j, 0o600)
    before = open(j, "rb").read()
    rc, out, err = run(["-n", "-u", j, "drop-caches"], capsys)
    assert rc == 1 and "0.5.x" in err and err.startswith("vfio-isolate: dry run:")
    open(j, "w").write("garbage\n")
    rc, out, err = run(["-n", "-u", j, "drop-caches"], capsys)
    assert rc == 1 and "not a vfio-isolate undo journal" in err
    os.chmod(j, 0o666)
    rc, out, err = run(["-n", "-u", j, "drop-caches"], capsys)
    assert rc == 1 and "writable by group or others" in err
    # a missing or empty file is fine, and is left alone
    os.unlink(j)
    assert run(["-n", "-u", j, "drop-caches"], capsys)[0] == 0 and not os.path.exists(j)
    open(j, "w").close()
    os.chmod(j, 0o600)
    assert run(["-n", "-u", j, "drop-caches"], capsys)[0] == 0 and os.path.getsize(j) == 0


def _journal_with_tail(j, tail):
    from vfio_isolate import journal
    open(j, "w").write(json.dumps(journal.HEADER) + "\n" + tail)
    os.chmod(j, 0o600)
    return open(j, "rb").read()


def test_undo_file_truncated_tail_is_reported_not_trimmed(host, j, capsys):
    before = _journal_with_tail(j, '{"undo": [{"action": "dro')
    rc, out, err = run(["-n", "-u", j, "drop-caches"], capsys)
    assert rc == 0, err
    assert f"would record undo in {j}" in out
    assert f"would drop truncated last line of {j}" in out
    assert open(j, "rb").read() == before  # not trimmed
    assert "dropping truncated" not in err


def test_undo_file_corrupt_record_refused_like_a_real_run(host, j, capsys):
    _journal_with_tail(j, "garbage\n")
    rc_dry, _, err_dry = run(["-n", "-u", j, "drop-caches"], capsys)
    rc_real, _, err_real = run(["-u", j, "drop-caches"], capsys)
    assert rc_dry == rc_real == 1
    assert "corrupt journal at record 1" in err_dry and "corrupt journal at record 1" in err_real


def test_undo_file_owned_by_the_user_is_refused_because_a_real_run_is_root(host, j, capsys, monkeypatch):
    from vfio_isolate import journal
    _journal_with_tail(j, "")
    monkeypatch.setattr(journal, "REAL_RUN_UID", 0)  # not the owner of the file: we are not root
    rc, out, err = run(["-n", "-u", j, "drop-caches"], capsys)
    assert rc == 1 and "is not owned by the current user" in err and err.startswith("vfio-isolate: dry run:")
    open(j, "w").close()  # an empty file is checked for ownership too
    os.chmod(j, 0o600)
    assert run(["-n", "-u", j, "drop-caches"], capsys)[0] == 1


def test_undo_file_unreadable_for_the_user_is_a_note_not_a_failure(host, j, capsys, monkeypatch):
    before = _journal_with_tail(j, "")
    real_open = os.open

    def deny(path, *a, **kw):  # a root-owned 0600 journal, read as a normal user
        if path == j:
            raise PermissionError(13, "Permission denied", path)
        return real_open(path, *a, **kw)
    monkeypatch.setattr(os, "open", deny)
    rc, out, err = run(["-n", "-u", j, "drop-caches"], capsys)
    assert rc == 0, err
    assert (f"would record undo in {j} (existing journal not readable as this user; "
            f"checked only in a real run)") in out
    assert open(j, "rb").read() == before


def test_undo_file_in_a_missing_directory_fails_like_a_real_run(host, tmp_path, capsys):
    path = str(tmp_path / "nodir" / "j")
    rc_dry, _, err_dry = run(["-n", "-u", path, "drop-caches"], capsys)
    rc_real, _, err_real = run(["-u", path, "drop-caches"], capsys)
    assert rc_dry == rc_real == 1
    assert f"undo file {path} does not exist" in err_dry and f"undo file {path} does not exist" in err_real
    assert not os.path.exists(tmp_path / "nodir")


def test_restore_with_dry_run_after_the_file_is_a_usage_error(host, j, capsys):
    assert main(["-u", j, "drop-caches"]) == 0
    host.mkcg("a")
    assert main(["-u", j, "cpuset-modify", "--cpus", "C0-3", "/a"]) == 0
    capsys.readouterr()
    before = open(j, "rb").read()
    cpus = (host.root / "sys/fs/cgroup/a/cpuset.cpus").read_text()
    rc, out, err = run(["restore", j, "-n"], capsys)
    assert rc == 2 and "No such command '-n'" in err
    assert open(j, "rb").read() == before  # journal unchanged
    assert (host.root / "sys/fs/cgroup/a/cpuset.cpus").read_text() == cpus  # nothing restored
    assert "would" not in out
