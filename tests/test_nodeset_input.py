import pytest

from vfio_isolate.cli import main
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet, NodeSetSyntaxError

ACTIVE_IRQ_ARGS = ["drop-caches", "irq-affinity", "mask"]


def run(fake_host, arg, capsys):
    rc = main(ACTIVE_IRQ_ARGS + [arg])
    err = capsys.readouterr().err
    return rc, err


def test_from_mask():
    assert set(CPUNodeSet.from_mask("3c")) == {2, 3, 4, 5}
    assert set(CPUNodeSet.from_mask("ff,0000000f")) == set(range(4)) | set(range(32, 40))
    assert set(CPUNodeSet.from_mask("FF")) == set(range(8))


@pytest.mark.parametrize("bad", ["", "xyz", "123456789", "ff,,0f", "ff,"])
def test_from_mask_rejects(bad):
    with pytest.raises(NodeSetSyntaxError):
        CPUNodeSet.from_mask(bad)


def test_reversed_range_is_syntax_error():
    with pytest.raises(NodeSetSyntaxError):
        CPUNodeSet("7-0")


def test_huge_range_is_syntax_error_quickly():
    with pytest.raises(NodeSetSyntaxError, match="too large"):
        CPUNodeSet("0-99999999999")


def test_huge_range_is_usage_error(fake_host, capsys):
    rc, err = run(fake_host, "C0-99999999999", capsys)
    assert rc == 2 and "too large" in err


def test_cpuless_numa_node_is_usage_error(fake_host, capsys):
    fake_host._write("sys/devices/system/node/node1/cpulist", "\n")
    rc, err = run(fake_host, "N1", capsys)
    assert rc == 2 and "no CPUs" in err
    assert fake_host.read("proc/sys/vm/drop_caches") == "0"


def test_empty_string_is_empty_set():
    assert not CPUNodeSet("")
    assert not CPUNodeSet("\n")


@pytest.mark.parametrize("arg", ["M3c", "Mff,0000000f", "MFF"])
def test_mask_accepted(fake_host, capsys, arg):
    # fake host has fewer CPUs than 40, so only check parsing via the callback
    from vfio_isolate.cli import cb_cpu_nodeset
    import click
    if arg == "Mff,0000000f":
        with pytest.raises(click.BadParameter, match="do not exist"):
            cb_cpu_nodeset(None, None, arg)
    else:
        assert cb_cpu_nodeset(None, None, arg) is not None


def test_mask_values(fake_host):
    from vfio_isolate.cli import cb_cpu_nodeset
    assert set(cb_cpu_nodeset(None, None, "M3c")) == {2, 3, 4, 5}


@pytest.mark.parametrize("arg,text", [
    ("C10000000", "10000000 do not exist"),
    ("C000000ff", "C000000ff"),
    ("C7-0", "7-0"),
    ("C", "empty"),
    ("N", "empty"),
    ("M", "empty"),
    ("M0", "empty"),
    ("Mxyz", "Mxyz"),
    ("C0-3,,5", "C0-3,,5"),
    ("X1", "C, N or M"),
])
def test_usage_errors_change_nothing(fake_host, capsys, arg, text):
    rc, err = run(fake_host, arg, capsys)
    assert rc == 2
    assert text in err
    assert "Traceback" not in err
    assert fake_host.read("proc/sys/vm/drop_caches") == "0"


def test_numa_option_rejects_cpu_forms(fake_host, capsys):
    rc = main(["cpuset-modify", "--mems", "C0", "/x"])
    assert rc == 2
    assert "must start with N" in capsys.readouterr().err


def test_numa_complement(fake_host):
    fake_host._write("sys/devices/system/node/possible", "0-1\n")
    NUMANodeSet.possible_nodes.value = None
    assert set(NUMANodeSet({0}).negation()) == {1}
    assert set(CPUNodeSet({0}).negation()) == set(range(1, 8))
