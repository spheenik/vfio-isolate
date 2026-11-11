"""Scenario tests for kthread-affinity (openspec/changes/kthread-affinity/specs/kthread-affinity)."""
import errno
import os

import pytest

from vfio_isolate import kthread
from vfio_isolate.cli import main
from vfio_isolate.journal import read_journal


def run(*argv):
    return main(list(argv))


@pytest.fixture
def host(fake_host_factory):
    h = fake_host_factory(num_cpus=32)
    h.add_kthread(2, "kthreadd")
    h.add_kthread(30, "kswapd0")
    h.add_kthread(31, "khugepaged")
    h.add_process(1, "systemd")
    h.add_process(500, "sshd")
    return h


def aff(host, *pids):
    return [host.thread_affinity(p) for p in pids]


def lines(err):
    return [l for l in err.splitlines() if l]


def test_mask_and_restore(host, tmp_path):
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C8-15,24-31") == 0
    assert aff(host, 2, 30, 31) == ["0-7,16-23"] * 3
    assert run("restore", j) == 0
    assert aff(host, 2, 30, 31) == ["0-31"] * 3


def test_add(host, tmp_path):
    for pid in (2, 30, 31):
        host.threads[pid]["affinity"] = type(host.threads[pid]["affinity"])("0-7")
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "add", "C8-9") == 0
    assert aff(host, 2, 30, 31) == ["0-9"] * 3
    assert run("restore", j) == 0
    assert aff(host, 2, 30, 31) == ["0-7"] * 3


def test_normal_processes_are_ignored(host, tmp_path):
    assert run("-u", str(tmp_path / "j"), "kthread-affinity", "mask", "C8-15") == 0
    assert aff(host, 1, 500) == ["0-31", "0-31"]
    assert {pid for pid, _ in host.setaffinity_calls} == {2, 30, 31}


def test_kthreadd_first(host):
    host.add_kthread(1000, "late")
    host.add_kthread(3, "rcu_gp")
    assert [t.pid for t in kthread.list_kernel_threads()] == [2, 3, 30, 31, 1000]


def test_thread_without_remaining_cpu_gets_all_but_masked(host, tmp_path):
    host.threads[30]["affinity"] = type(host.threads[30]["affinity"])("8-15")
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C8-15") == 0
    assert aff(host, 30) == ["0-7,16-31"]
    assert run("restore", j) == 0
    assert aff(host, 30) == ["8-15"]


def test_masking_every_cpu_is_refused(host, capsys):
    assert run("kthread-affinity", "mask", "C0-31") == 1
    assert "no CPU would remain" in capsys.readouterr().err
    assert host.setaffinity_calls == []


def test_per_cpu_threads_are_skipped(host, tmp_path, capsys):
    host.add_kthread(40, "ksoftirqd/0", affinity="0", percpu=True)
    host.add_kthread(41, "ksoftirqd/1", affinity="1", percpu=True)
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C8-15") == 0
    assert lines(capsys.readouterr().err) == []
    assert aff(host, 2, 30, 31, 40, 41) == ["0-7,16-31"] * 3 + ["0", "1"]
    assert {pid for pid, _ in host.setaffinity_calls} == {2, 30, 31}
    assert {s.params.pid for r in read_journal(j) for s in r} == {2, 30, 31}
    assert run("restore", j) == 0
    assert lines(capsys.readouterr().err) == []
    assert aff(host, 2, 30, 31) == ["0-31"] * 3


def test_kthreadd_is_listed_even_with_no_setaffinity_flag(host):
    host._write("proc/2/stat", "2 (kthreadd) S 0 0 0 0 -1 %d 0 0 0 0 0 0 0 0 20 0 1 0 5 0 0\n"
                % (host.PF_KTHREAD | host.PF_NO_SETAFFINITY))
    assert kthread.list_kernel_threads()[0].pid == 2


def test_thread_refusing_with_einval_is_counted(host, tmp_path, capsys):
    # a thread that is not flagged but refuses anyway (it became per-CPU meanwhile)
    host.add_kthread(40, "odd", affinity="0", refuses=True)
    assert run("-u", str(tmp_path / "j"), "kthread-affinity", "mask", "C8-15") == 0
    assert lines(capsys.readouterr().err) == ["vfio-isolate: 1 per-CPU kernel thread cannot be moved"]
    assert run("-v", "kthread-affinity", "mask", "C8-15") == 0
    assert lines(capsys.readouterr().err) == [
        "vfio-isolate: 1 per-CPU kernel thread cannot be moved: 40 (odd)"]


def test_mask_fallback_uses_online_cpus(host, tmp_path):
    (host.root / "sys/devices/system/cpu/online").write_text("0-15\n")
    host.threads[30]["affinity"] = type(host.threads[30]["affinity"])("8-15")
    assert run("-u", str(tmp_path / "j"), "kthread-affinity", "mask", "C8-15") == 0
    assert aff(host, 30) == ["0-7"]  # not the possible CPUs 16-31


def test_masking_every_online_cpu_is_refused(host, capsys):
    (host.root / "sys/devices/system/cpu/online").write_text("0-15\n")
    assert run("kthread-affinity", "mask", "C0-15") == 1
    assert "no CPU would remain" in capsys.readouterr().err
    assert host.setaffinity_calls == []


def restore_ps(j):
    return {s.params.pid: s.params for r in read_journal(j) for s in r}


def test_journal_records_starttime_and_comm(host, tmp_path):
    host._write("proc/30/stat", "30 (kswapd0) S 2 0 0 0 -1 %d 0 0 0 0 0 0 0 0 20 0 1 0 777 0 0\n"
                % host.PF_KTHREAD)
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C8-15") == 0
    assert (restore_ps(j)[30].starttime, restore_ps(j)[30].comm) == (777, "kswapd0")


def test_restore_ignores_reused_pid(host, tmp_path, capsys):
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C8-15") == 0
    capsys.readouterr()
    host.setaffinity_calls.clear()
    # 30 is now a normal process, 31 a different kernel thread (new starttime)
    host.add_process(30, "bash", affinity="0-7")
    host.add_kthread(31, "other", affinity="0-7", starttime=99)
    assert run("restore", j) == 0
    assert lines(capsys.readouterr().err) == ["vfio-isolate: 2 kernel threads exited before they could be moved"]
    assert {pid for pid, _ in host.setaffinity_calls} == {2}
    assert aff(host, 30, 31) == ["0-7", "0-7"]
    assert not os.path.exists(j)


def test_thread_exits_during_run(host, tmp_path, monkeypatch, capsys):
    j = str(tmp_path / "j")
    real = kthread.get_affinity

    def get(pid):
        if pid == 31 and pid in host.threads:  # still listed, gone by the time it is touched
            host.exit_thread(31)
        return real(pid)
    monkeypatch.setattr(kthread, "get_affinity", get)
    assert run("-u", j, "kthread-affinity", "mask", "C8-15") == 0
    assert lines(capsys.readouterr().err) == ["vfio-isolate: 1 kernel thread exited before it could be moved"]
    assert aff(host, 2, 30) == ["0-7,16-31"] * 2
    recorded = [s.params.pid for r in read_journal(j) for s in r]
    assert set(recorded) == {2, 30}


def test_thread_gone_before_restore(host, tmp_path, capsys):
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C8-15") == 0
    host.exit_thread(30)
    capsys.readouterr()
    assert run("restore", j) == 0
    assert lines(capsys.readouterr().err) == ["vfio-isolate: 1 kernel thread exited before it could be moved"]
    assert aff(host, 2, 31) == ["0-31"] * 2
    assert not os.path.exists(j)


def test_unexpected_errno_warns_once_and_total_failure_exits_1(host, monkeypatch, capsys):
    def boom(pid, cpus):
        raise OSError(errno.EPERM, "x")
    monkeypatch.setattr(kthread, "set_affinity", boom)
    assert run("kthread-affinity", "mask", "C8-15") == 1
    err = lines(capsys.readouterr().err)
    assert err[0] == "vfio-isolate: warning: kernel thread 2 (kthreadd): Operation not permitted"
    assert "vfio-isolate: kthread-affinity: no kernel thread could be changed" in err


def test_unexpected_errno_in_restore_keeps_the_step(host, tmp_path, monkeypatch, capsys):
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C8-15") == 0
    real = kthread.set_affinity

    def fail_30(pid, cpus):
        if pid == 30:
            raise OSError(errno.EPERM, "x")
        return real(pid, cpus)
    monkeypatch.setattr(kthread, "set_affinity", fail_30)
    capsys.readouterr()
    assert run("restore", j) == 1
    assert [s.params.pid for r in read_journal(j) for s in r] == [30]
    assert aff(host, 2, 31) == ["0-31"] * 2


def test_isolated_partition_is_refused(host, capsys):
    host.set_workqueue("0-31", isolated="8-15")
    for op in ("add", "mask"):
        assert run("kthread-affinity", op, "C8-15") == 1
        err = capsys.readouterr().err
        assert "CPUs 8-15 are in isolated cpuset partitions" in err
        assert "kernel already keeps kernel threads off them" in err
    assert host.setaffinity_calls == []
    assert aff(host, 2, 30, 31) == ["0-31"] * 3


def test_chain_kthread_then_partition_restores_fully(host, tmp_path):
    host.patch_cgroup_fs()
    host.mkcg("x", cpus=None)
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C4-7", "cpuset-modify", "--partition", "isolated",
               "--cpus", "C4-7", "/x") == 0
    assert aff(host, 2) == ["0-3,8-31"]
    assert run("restore", j) == 0
    assert aff(host, 2, 30, 31) == ["0-31"] * 3


def test_partition_then_kthread_is_refused(host, tmp_path, capsys):
    host.patch_cgroup_fs()
    host.mkcg("x", cpus=None)
    j = str(tmp_path / "j")
    assert run("-u", j, "cpuset-modify", "--partition", "isolated", "--cpus", "C4-7", "/x") == 0
    assert run("kthread-affinity", "mask", "C2") == 1
    assert "CPUs 4-7 are in isolated cpuset partitions" in capsys.readouterr().err
    assert host.setaffinity_calls == []


# -- the /proc/<pid>/stat parser ---------------------------------------------------------

@pytest.mark.parametrize("comm", ["kworker/0:1H", "a b", "x) S 2 (y", "(weird)", "kworker/u16:2-events_unbound"])
def test_parse_stat_with_tricky_comm(comm):
    flags = 0x00208040
    text = f"123 ({comm}) S 2 0 0 0 -1 {flags} 0 0 0 0 0 0 0 0 20 0 1 0 5 0 0\n"
    assert kthread.parse_stat(text) == (comm, flags, 5)


def test_tricky_comm_threads_are_listed(host):
    host.add_kthread(60, "a) S 2 (b")
    host.add_process(61, "cat) (dog")
    assert [(t.pid, t.comm) for t in kthread.list_kernel_threads()][-1] == (60, "a) S 2 (b")
    assert 61 not in {t.pid for t in kthread.list_kernel_threads()}


def test_unreadable_stat_is_skipped(host):
    (host.root / "proc/77").mkdir()
    (host.root / "proc/77/stat").write_text("garbage")
    (host.root / "proc/78").mkdir()  # no stat file: exited meanwhile
    assert 77 not in {t.pid for t in kthread.list_kernel_threads()}


def test_journal_records_previous_affinity(host, tmp_path):
    host.threads[30]["affinity"] = type(host.threads[30]["affinity"])("4-20")
    j = str(tmp_path / "j")
    assert run("-u", j, "kthread-affinity", "mask", "C8-15") == 0
    steps = {s.params.pid: s.params for r in read_journal(j) for s in r}
    assert steps[2].operation.name == "restore" and steps[2].cpus.to_list_form() == "0-31"
    assert steps[30].cpus.to_list_form() == "4-20"
