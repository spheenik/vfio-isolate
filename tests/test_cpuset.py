import os

import pytest

from vfio_isolate.cpuset import CPUSet, PartitionInvalidError
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet

CG = "sys/fs/cgroup"


def snapshot(root):
    snap = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            st = os.stat(p)
            with open(p) as f:
                snap[p] = (f.read(), st.st_mtime_ns)
    return snap


def test_create_enables_cpuset_on_ancestors_only(fake_host):
    fake_host.patch_cgroup_fs()
    fake_host.mkcg("a")
    fake_host.mkcg("a/b")
    (fake_host.root / CG / "a/b/cgroup.subtree_control").write_text("memory\n")
    CPUSet("/a/b/c").create(cpus=CPUNodeSet("0-3"))
    assert fake_host.read(f"{CG}/cgroup.subtree_control") == "+cpuset"
    assert fake_host.read(f"{CG}/a/cgroup.subtree_control") == "+cpuset"
    assert fake_host.read(f"{CG}/a/b/cgroup.subtree_control") == "+cpuset"
    # the target's own subtree_control is untouched
    assert fake_host.read(f"{CG}/a/b/c/cgroup.subtree_control") == "\n"
    assert fake_host.read(f"{CG}/a/b/c/cpuset.cpus").strip() == "0-3"


def test_already_enabled_is_not_written(fake_host):
    fake_host.mkcg("a")
    for rel in ("", "a/"):
        (fake_host.root / CG / (rel + "cgroup.subtree_control")).write_text("memory cpuset pids\n")
    CPUSet("a").set_cpus(CPUNodeSet("1"))
    assert fake_host.read(f"{CG}/cgroup.subtree_control") == "memory cpuset pids\n"
    assert fake_host.read(f"{CG}/a/cgroup.subtree_control") == "memory cpuset pids\n"


def test_cpuset_token_must_match_exactly(fake_host):
    fake_host.mkcg("a")
    (fake_host.root / CG / "cgroup.subtree_control").write_text("cpuset.foo\n")
    CPUSet("a").set_mems(NUMANodeSet("0"))
    assert fake_host.read(f"{CG}/cgroup.subtree_control") == "+cpuset"


def test_setters_ensure_path_but_not_own(fake_host):
    fake_host.mkcg("a")
    fake_host.mkcg("a/b")
    CPUSet("a/b").set_mems(NUMANodeSet("0"))
    assert fake_host.read(f"{CG}/cgroup.subtree_control") == "+cpuset"
    assert fake_host.read(f"{CG}/a/cgroup.subtree_control") == "+cpuset"
    assert fake_host.read(f"{CG}/a/b/cgroup.subtree_control") == "\n"


def test_parents_terminates(fake_host):
    assert [c.name() for c in CPUSet("a/b/c").parents()] == ["/", "/a", "/a/b"]
    assert list(CPUSet().parents()) == []


def test_getters_do_not_write(fake_host):
    fake_host.mkcg("a")
    (fake_host.root / CG / "a/cpuset.cpus.partition").write_text("member\n")
    cs = CPUSet("a")
    before = snapshot(fake_host.root)
    cs.get_cpus(), cs.get_mems(), cs.get_configured_cpus(), cs.get_configured_mems()
    cs.get_partition()
    assert snapshot(fake_host.root) == before


def test_empty_nodeset_parses_and_writes_newline(fake_host):
    assert len(CPUNodeSet("\n")) == 0
    assert len(NUMANodeSet("")) == 0
    fake_host.mkcg("a")
    cs = CPUSet("a")
    cs.set_cpus(CPUNodeSet("2-3"))
    cs.set_cpus(CPUNodeSet())
    cs.set_mems(NUMANodeSet("0"))
    cs.set_mems(NUMANodeSet())
    assert fake_host.read(f"{CG}/a/cpuset.cpus") == "\n"
    assert fake_host.read(f"{CG}/a/cpuset.mems") == "\n"


def test_configured_vs_effective(fake_host):
    fake_host.mkcg("a", cpus="0-7", mems="0")
    cs = CPUSet("a")
    assert not cs.get_configured_cpus() and not cs.get_configured_mems()
    assert cs.get_cpus().to_list_form() == "0-7"
    cs.set_cpus(CPUNodeSet("2-3"))
    assert cs.get_configured_cpus().to_list_form() == "2-3"


def test_mkcg_inherits_effective(fake_host):
    fake_host.mkcg("a", cpus="1-2", mems="0")
    d = fake_host.mkcg("a/b", cpus=None, mems=None)
    assert (d / "cpuset.cpus.effective").read_text() == "1-2\n"
    assert (d / "cpuset.mems.effective").read_text() == "0\n"
    assert (d / "cpuset.cpus").read_text() == "\n"


def test_create_without_cpus_inherits(fake_host):
    fake_host.patch_cgroup_fs()
    CPUSet("a").create()
    assert fake_host.read(f"{CG}/a/cpuset.cpus").strip() == ""
    assert fake_host.read(f"{CG}/a/cpuset.mems").strip() == ""


@pytest.mark.parametrize("text,expected", [
    ("member\n", ("member", None)),
    ("root\n", ("root", None)),
    ("isolated\n", ("isolated", None)),
    ("isolated invalid (xyz)\n", ("isolated", "xyz")),
    ("root invalid (Invalid cpu list in cpuset.cpus.exclusive)\n",
     ("root", "Invalid cpu list in cpuset.cpus.exclusive")),
    ("root invalid\n", ("root", "")),
])
def test_get_partition(fake_host, text, expected):
    fake_host.mkcg("a")
    (fake_host.root / CG / "a/cpuset.cpus.partition").write_text(text)
    assert CPUSet("a").get_partition() == expected


def test_set_partition_ok_and_invalid(fake_host):
    fake_host.mkcg("a")
    f = fake_host.root / CG / "a/cpuset.cpus.partition"
    f.write_text("member\n")
    cs = CPUSet("a")
    cs.set_partition("member")
    assert f.read_text() == "member"
    # the fake does not validate: simulate the kernel answering invalid after the write
    f.write_text("isolated invalid (no cpus)\n")
    real_open = cs.open

    def fake_open(file, mode="r"):
        return real_open(file, mode) if mode == "r" else open(os.devnull, "w")
    cs.open = fake_open
    with pytest.raises(PartitionInvalidError) as ei:
        cs.set_partition("isolated")
    assert ei.value.args[0] == "no cpus"
