"""Every README invocation with -n on a fake host: nothing is written, nothing is created.

Unlike test_readme.py, Executor.run is not patched: the dry-run path runs for real.
"""
import os
import shutil
from pathlib import Path

import pytest

from readme_examples import extract
from vfio_isolate import journal
from vfio_isolate.cli import main

README = Path(__file__).resolve().parent.parent / "README.md"
READ_ONLY_VERBS = {"show", "is-active", "is-system-running", "is-enabled", "cat", "status"}

# README line -> (reason, expected exit status) for invocations that cannot succeed on the
# fake host even as a preview. Empty: every example previews cleanly.
EXPECTED_FAILURES = {}


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


def test_readme_invocations_dry_run_is_read_only(fake_host_factory, tmp_path, capsys):
    host = fake_host_factory(num_cpus=32, governors="performance powersave")
    host.patch_cgroup_fs()
    sd = host.enable_systemd(units={"system.slice": "/system.slice", "user.slice": "/user.slice",
                                    "init.scope": "/init.scope", "machine.slice": "/machine.slice"})
    for cg in ("host", "vm"):
        host.mkcg(cg, cpus="0-31")
    for n in (24, 25, 41):
        host.add_irq(n, "0-31")
    (tmp_path / "undo").mkdir()
    invocations = extract(README.read_text())
    assert len(invocations) >= 5
    ran = 0
    for no, argv in invocations:
        assert not any("$" in a for a in argv), f"README.md:{no}: unsubstituted variable in {argv}"
        argv = list(argv)
        is_restore = "restore" in argv
        for i, a in enumerate(argv):
            if a in ("-u", "--undo-file") and i + 1 < len(argv):
                argv[i + 1] = str(tmp_path / "undo" / Path(argv[i + 1]).name)
        if is_restore:
            argv[-1] = str(tmp_path / "undo" / Path(argv[-1]).name)  # restore [-n] FILE
            # a journal with real records: two small real commands on the fake host, recorded
            # with -u into that path, so the preview has steps to describe
            path = argv[-1]
            if os.path.exists(path):
                os.unlink(path)
            for n in (24, 25, 41):
                host.add_irq(n, "0-31")  # earlier restore examples left them changed
            (host.root / "sys/fs/cgroup/host/cpuset.cpus").write_text("0-31\n")
            assert main(["-u", path, "cpuset-modify", "--cpus", "C0-15", "/host"]) == 0
            assert main(["-u", path, "irq-affinity", "mask", "C0-3"]) == 0, capsys.readouterr()
            capsys.readouterr()
            (host.root / "run/vfio-isolate.lock").unlink()  # left by the real runs above
            assert len(journal.read_journal(path)) >= 2
        # the README creates /vfio-test in some examples and uses the existing one in others
        vfio_test = host.root / "sys/fs/cgroup/vfio-test"
        creates = "cpuset-create" in argv and "/vfio-test" in argv
        if creates and vfio_test.exists():
            shutil.rmtree(vfio_test)
        elif not creates and not vfio_test.exists():
            host.mkcg("vfio-test", cpus="0-31")
        before = snapshot(host.root)
        # listing and content (bytes) of every file in the undo directory
        def undo_state():
            return {n: (tmp_path / "undo" / n).read_bytes() for n in sorted(os.listdir(tmp_path / "undo"))}
        undo_before = undo_state()
        calls_before = len(sd.calls)
        rc = main(["-n"] + argv)
        out = capsys.readouterr()
        if no in EXPECTED_FAILURES:
            reason, want = EXPECTED_FAILURES[no]
            assert rc == want, f"README.md:{no}: {argv}: {out.err}"
        else:
            assert rc == 0, f"README.md:{no}: {argv}: {out.err}"
        assert snapshot(host.root) == before, f"README.md:{no}: -n changed the fake host: {argv}"
        assert undo_state() == undo_before, f"README.md:{no}: -n created or changed a journal: {argv}"
        if is_restore:
            assert "would restore" in out.out and "would set cpuset /host" in out.out \
                and "would change affinity of" in out.out, f"README.md:{no}: {out.out}"
        assert not os.path.exists(host.root / "run/vfio-isolate.lock"), f"README.md:{no}: lock file"
        new_calls = sd.calls[calls_before:]
        assert {c[0] for c in new_calls if c} <= READ_ONLY_VERBS, f"README.md:{no}: {new_calls}"
        ran += 1
    assert ran == len(invocations)
