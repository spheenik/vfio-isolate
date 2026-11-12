"""Scenario tests for irq-affinity's default affinity (openspec/changes/irq-default-affinity)."""
import os

import pytest

from vfio_isolate.action import DefaultAffinityOperation, IRQDefaultAffinity
from vfio_isolate.cli import main
from vfio_isolate.journal import read_journal


@pytest.fixture
def host(fake_host_factory):
    h = fake_host_factory(num_cpus=32)
    h.add_irq(24, "0-31")
    h.add_irq(25, "0-31")
    return h


@pytest.fixture
def j(tmp_path):
    return str(tmp_path / "undo.journal")


def run(*argv):
    return main(list(argv))


def test_mask_and_restore(host, j):
    assert run("-u", j, "irq-affinity", "mask", "C8-15") == 0
    assert host.default_irq_affinity().to_list_form() == "0-7,16-31"
    assert run("restore", j) == 0
    assert host.default_irq_affinity().to_list_form() == "0-31"


def test_overlapping_vms(host, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    assert run("-u", a, "irq-affinity", "mask", "C8-15") == 0
    assert run("-u", b, "irq-affinity", "mask", "C16-23") == 0
    assert run("restore", a) == 0
    assert host.default_irq_affinity().to_list_form() == "0-15,24-31"


def test_add_records_only_new_cpus(host, j):
    host.set_default_irq_affinity("0-7")
    assert run("-u", j, "irq-affinity", "add", "C4-11") == 0
    assert host.default_irq_affinity().to_list_form() == "0-11"
    undo = [e.params for r in read_journal(j) for e in r if e.action is IRQDefaultAffinity]
    assert [(u.operation, u.cpus.to_list_form()) for u in undo] == [(DefaultAffinityOperation.mask, "8-11")]
    assert run("restore", j) == 0
    assert host.default_irq_affinity().to_list_form() == "0-7"


def test_unchanged_records_nothing(host, j):
    assert run("-u", j, "irq-affinity", "add", "C0-3") == 0
    with open(j) as f:
        assert "irq-default-affinity" not in f.read()


def test_default_written_before_irqs(host, monkeypatch):
    from vfio_isolate import irq
    order = []
    real_default, real_irq = irq.write_default_affinity, irq.IRQ.set_affinity
    monkeypatch.setattr(irq, "write_default_affinity",
                        lambda c: (order.append("default"), real_default(c))[1])
    monkeypatch.setattr(irq.IRQ, "set_affinity",
                        lambda self, c: (order.append(self.number), real_irq(self, c))[1])
    assert run("irq-affinity", "mask", "C8-15") == 0
    assert order[0] == "default" and sorted(order[1:]) == [24, 25]


def test_file_missing(host, j, capsys):
    os.remove(host.root / "proc/irq/default_smp_affinity")
    assert run("-u", j, "irq-affinity", "mask", "C8-15") == 0
    assert capsys.readouterr().out == ""
    with open(j) as f:
        assert "irq-default-affinity" not in f.read()
    assert not (host.root / "proc/irq/default_smp_affinity").exists()
    rc = run("-n", "irq-affinity", "mask", "C8-15")
    assert rc == 0
    assert "default IRQ affinity" not in capsys.readouterr().out


def test_refusal_changes_nothing(fake_host_factory, capsys):
    host = fake_host_factory(num_cpus=8)
    host.add_irq(24, "0-7")
    assert run("irq-affinity", "mask", "C0-7") == 1
    assert "default IRQ affinity" in capsys.readouterr().err
    assert host.default_irq_affinity().to_list_form() == "0-7"
    assert (host.root / "proc/irq/24/smp_affinity_list").read_text().strip() == "0-7"


def test_refusal_when_only_offline_cpus_remain(fake_host_factory, capsys):
    host = fake_host_factory(num_cpus=8)
    host.set_default_irq_affinity("0-15")  # 8-15 are not online
    assert run("irq-affinity", "mask", "C0-7") == 1
    assert host.default_irq_affinity().to_list_form() == "0-15"


def test_dry_run_preview_order(host, capsys):
    assert run("-n", "irq-affinity", "mask", "C8-15") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "would set default IRQ affinity: 0-31 -> 0-7,16-31"
    assert lines[1].startswith("would change affinity of ")
    assert host.default_irq_affinity().to_list_form() == "0-31"


def test_dry_run_unchanged_prints_nothing(host, capsys):
    assert run("-n", "irq-affinity", "add", "C0-3") == 0
    assert "default IRQ affinity" not in capsys.readouterr().out


def test_restore_preview_matches_refused_restore(host, j, capsys):
    host.set_default_irq_affinity("0-3")
    assert run("-u", j, "irq-affinity", "add", "C4-7") == 0
    host.set_default_irq_affinity("4-7")  # something else changed it: undo (mask 4-7) would empty it
    capsys.readouterr()
    assert run("-n", "restore", j) == 0
    out = capsys.readouterr().out
    assert "default IRQ affinity" in out and "refused" in out
    assert run("restore", j) == 1
    assert host.default_irq_affinity().to_list_form() == "4-7"
    undo = [e.params for r in read_journal(j) for e in r if e.action is IRQDefaultAffinity]
    assert [(u.operation, u.cpus.to_list_form()) for u in undo] == [(DefaultAffinityOperation.mask, "4-7")]


def test_more_than_32_cpus(fake_host_factory, j):
    h = fake_host_factory(num_cpus=40)
    h.add_irq(24, "0-39")
    path = h.root / "proc/irq/default_smp_affinity"
    path.write_text("ff,ffffffff\n")  # kernel style: unpadded high word
    assert h.default_irq_affinity().to_list_form() == "0-39"
    assert run("-u", j, "irq-affinity", "mask", "C32-39") == 0
    assert h.default_irq_affinity().to_list_form() == "0-31"
    assert path.read_text() == "ffffffff"
    assert run("restore", j) == 0
    assert h.default_irq_affinity().to_list_form() == "0-39"
    assert path.read_text() == "000000ff,ffffffff"
