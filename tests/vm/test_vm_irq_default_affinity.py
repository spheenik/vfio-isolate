"""irq-affinity and /proc/irq/default_smp_affinity against the guest's real kernel."""
import errno
import os

import pytest

from vfio_isolate.cli import main

pytestmark = pytest.mark.vm

DEFAULT = "/proc/irq/default_smp_affinity"


def _rd():
    with open(DEFAULT) as f:
        return f.read().strip()


def _online():
    with open("/sys/devices/system/cpu/online") as f:
        return f.read().strip()


def _irqs():
    out = {}
    for d in os.listdir("/proc/irq"):
        if d.isdigit():
            try:
                with open(f"/proc/irq/{d}/smp_affinity_list") as f:
                    out[d] = f.read().strip()
            except OSError:
                pass
    return out


def test_kernel_refuses_empty_default(capsys):
    orig = _rd()
    try:
        with pytest.raises(OSError) as ei:
            with open(DEFAULT, "w") as f:
                f.write("0")
        with capsys.disabled():
            print("\nDEFAULT_AFFINITY_EMPTY_ERRNO", errno.errorcode.get(ei.value.errno))
        # observed in the guest: EINVAL (no online CPU in the mask)
        assert ei.value.errno == errno.EINVAL
    finally:
        with open(DEFAULT, "w") as f:
            f.write(orig)


def test_mask_sets_default_and_restore_brings_it_back(tmp_path):
    j = str(tmp_path / "journal")
    before = _rd()
    assert main(["-u", j, "irq-affinity", "mask", "C0"]) == 0
    try:
        assert _rd() != before
        assert int(_rd().replace(",", ""), 16) & 1 == 0
    finally:
        assert main(["restore", j]) == 0
    assert _rd() == before


def test_mask_of_all_online_cpus_is_refused(tmp_path):
    j = str(tmp_path / "journal")
    before, irqs = _rd(), _irqs()
    assert main(["-u", j, "irq-affinity", "mask", "C" + _online()]) == 1
    assert _rd() == before
    assert _irqs() == irqs
