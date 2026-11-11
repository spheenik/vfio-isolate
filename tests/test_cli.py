from vfio_isolate.cli import main


def test_help_without_cgroups(fake_host, capsys):
    fake_host.set_layout("none")
    assert main(["--help"]) == 0
    assert "Usage" in capsys.readouterr().out


def test_drop_caches_on_v1(fake_host):
    fake_host.set_layout("v1")
    assert main(["drop-caches"]) == 0
    assert fake_host.read("proc/sys/vm/drop_caches") == "3"


def test_hybrid_fails_before_any_action(fake_host, capsys):
    fake_host.set_layout("hybrid")
    rc = main(["drop-caches", "cpuset-modify", "--cpus", "C0-3", "/host"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "bound to a cgroup v1" in err and "0.5" in err
    assert fake_host.read("proc/sys/vm/drop_caches") == "0"


def test_no_cgroup2(fake_host, capsys):
    fake_host.set_layout("none")
    assert main(["cpuset-modify", "--cpus", "C0-3", "/host"]) == 1
    assert "cgroup v2 not found" in capsys.readouterr().err


def test_no_cpuset_controller(fake_host, capsys):
    fake_host.set_layout("no-cpuset")
    assert main(["cpuset-modify", "--cpus", "C0-3", "/host"]) == 1
    assert "cpuset controller not available" in capsys.readouterr().err


def test_removed_v1_option_rejected(fake_host, capsys):
    cg = fake_host.mkcg("host")
    rc = main(["cpuset-modify", "--cpu-exclusive", "--cpus", "C0-3", "/host"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "--cpu-exclusive" in err
    assert "Traceback" not in err
    assert (cg / "cpuset.cpus").read_text() == "\n"


def test_modify_writes_cpus_and_mems(fake_host):
    cg = fake_host.mkcg("host")
    assert main(["cpuset-modify", "--cpus", "C0-3", "--mems", "N0", "/host"]) == 0
    assert (cg / "cpuset.cpus").read_text() == "0-3"
    assert (cg / "cpuset.mems").read_text() == "0"


def test_modify_help(fake_host, capsys):
    assert main(["cpuset-modify", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--cpus" in out and "--mems" in out
    assert "cgroup v1" not in out and "exclusive" not in out


def test_undo_file_and_restore(fake_host, tmp_path):
    cg = fake_host.mkcg("host", cpus="0-7")
    undo = str(tmp_path / "undo")
    assert main(["-u", undo, "cpuset-modify", "--cpus", "C0-3", "/host"]) == 0
    assert (cg / "cpuset.cpus").read_text() == "0-3"
    # the undo captures the configured cpuset.cpus (empty = inherit)
    # (detailed journal scenarios live in test_undo.py)
    assert main(["restore", undo]) == 0
    assert (cg / "cpuset.cpus").read_text() == "\n"


def test_restore_checked_before_executing(fake_host, tmp_path, capsys):
    fake_host.mkcg("host")
    undo = str(tmp_path / "undo")
    assert main(["-u", undo, "cpuset-modify", "--cpus", "C0-3", "/host"]) == 0
    fake_host.set_layout("hybrid")
    # drop-caches would run first; the pre-check (which looks into the restore's
    # steps) must stop everything before it
    assert main(["drop-caches", "restore", undo]) == 1
    assert "bound to a cgroup v1" in capsys.readouterr().err
    assert fake_host.read("proc/sys/vm/drop_caches") == "0"


def test_removed_option_in_chain_runs_nothing(fake_host, capsys):
    fake_host.mkcg("host")
    rc = main(["drop-caches", "cpuset-modify", "-ce", "--cpus", "C0-3", "/host"])
    assert rc == 2
    assert fake_host.read("proc/sys/vm/drop_caches") == "0"


def test_create_help(fake_host, capsys):
    assert main(["cpuset-create", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--cpus" in out and "--mems" in out
    assert "cgroup v1" not in out and "exclusive" not in out


# cpuset-commands scenarios for --partition (cgroup2-cpuset); fake-only

def test_modify_help_shows_partition_experimental(fake_host, capsys):
    """fake-only."""
    assert main(["cpuset-modify", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--partition" in out and "EXPERIMENTAL" in out
    assert "member" in out and "isolated" in out
    assert main(["cpuset-create", "--help"]) == 0
    assert "--partition" not in capsys.readouterr().out


def test_invalid_partition_value_is_usage_error(fake_host, capsys):
    """Invalid --partition: usage error listing the choices, nothing in the chain ran.
    fake-only."""
    cg = fake_host.mkcg("host")
    rc = main(["drop-caches", "cpuset-modify", "--partition", "exclusive", "/host"])
    err = capsys.readouterr().err
    assert rc == 2
    for choice in ("member", "root", "isolated"):
        assert choice in err
    assert fake_host.read("proc/sys/vm/drop_caches") == "0"
    assert (cg / "cpuset.cpus").read_text() == "\n"


def test_systemctl_error_exits_1(fake_host, capsys):
    """A failing systemctl call is a clean exit 1 without traceback. fake-only."""
    from vfio_isolate.systemd import SystemctlError
    sd = fake_host.enable_systemd(units={"machine.slice": "/machine.slice"})

    def boom(args):
        if args and args[0] == "set-property":
            raise SystemctlError("systemctl set-property failed (1): nope")
        return sd.run(args)
    fake_host._monkeypatch.setattr("vfio_isolate.systemd._run", boom)
    assert main(["cpuset-modify", "--cpus", "C0-3", "/machine.slice"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("vfio-isolate: ") and "nope" in err and "Traceback" not in err
