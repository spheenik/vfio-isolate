"""irqbalance warning (openspec/changes/kernel-noise/specs/irq-affinity)."""
import psutil
import pytest

from vfio_isolate import irq
from vfio_isolate.cli import main

REAL_IRQBALANCE_RUNNING = irq.irqbalance_running  # fake_host stubs it out


class P:
    def __init__(self, name=None, exc=None):
        self._name, self._exc = name, exc

    @property
    def info(self):
        if self._exc:
            raise self._exc
        return {"name": self._name}


def patch(monkeypatch, procs):
    monkeypatch.setattr(irq, "irqbalance_running", REAL_IRQBALANCE_RUNNING)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(procs))


@pytest.fixture
def host(fake_host_factory):
    h = fake_host_factory(num_cpus=8)
    for n in range(5):
        h.add_irq(n, "0-7")
    return h


def test_running_warns_once_and_still_changes(host, monkeypatch, capsys):
    patch(monkeypatch, [P("bash"), P("irqbalance")])
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    err = capsys.readouterr().err
    assert err.count("irqbalance is running") == 1
    assert "vfio-isolate: warning: irqbalance is running" in err
    assert "IRQBALANCE_BANNED_CPULIST" in err
    for n in range(5):
        assert host.read(f"proc/irq/{n}/smp_affinity_list").strip() == "4-7"


def test_not_running_no_warning(host, monkeypatch, capsys):
    patch(monkeypatch, [P("bash"), P("sshd")])
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    assert "irqbalance" not in capsys.readouterr().err


def test_access_denied_ignored(host, monkeypatch, capsys):
    patch(monkeypatch, [P(exc=psutil.AccessDenied()), P(exc=psutil.NoSuchProcess(1)), P("irqbalance")])
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    assert capsys.readouterr().err.count("irqbalance is running") == 1
    patch(monkeypatch, [P(exc=psutil.AccessDenied()), P("sshd")])
    assert main(["irq-affinity", "mask", "C0-3"]) == 0
    assert "irqbalance" not in capsys.readouterr().err
