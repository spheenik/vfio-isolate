import shutil

from vfio_isolate.cli import main


def set_available(fake_host, text, cpus=range(8)):
    for n in cpus:
        fake_host.root.joinpath(
            f"sys/devices/system/cpu/cpu{n}/cpufreq/scaling_available_governors"
        ).write_text(text)


def test_unknown_governor_stops_chained_run(fake_host, capsys):
    set_available(fake_host, "performance powersave\n")
    rc = main(["drop-caches", "cpu-governor", "schedutil", "C0-3"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "performance powersave" in err
    assert fake_host.read("proc/sys/vm/drop_caches") == "0"


def test_cpu_without_cpufreq(fake_host, capsys):
    shutil.rmtree(fake_host.root / "sys/devices/system/cpu/cpu5/cpufreq")
    rc = main(["cpu-governor", "performance", "C4-5"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "CPUs 5 have no cpufreq" in err
    assert fake_host.read("sys/devices/system/cpu/cpu4/cpufreq/scaling_governor") == "powersave\n"


def test_valid_governor_is_set(fake_host):
    assert main(["cpu-governor", "performance", "C0-3"]) == 0
    for n in range(4):
        assert fake_host.read(
            f"sys/devices/system/cpu/cpu{n}/cpufreq/scaling_governor").strip() == "performance"
