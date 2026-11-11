import json
import os

import pytest

from vfio_isolate import journal
from vfio_isolate.action import (ACTIONS, Execution, CompactMemory, CPUGovernor, CPUSetCreate,
                                 CPUSetDelete, CPUSetModify, DropCaches, IRQAffinity,
                                 IRQAffinityOperation, MoveTasks)
from vfio_isolate.cpu import CPU
from vfio_isolate.irq import IRQ
from vfio_isolate.journal import JournalError, encode, decode
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet

HEADER = '{"format": "vfio-isolate-undo", "version": 1}\n'


def all_executions():
    return [
        Execution(CompactMemory, CompactMemory.Param()),
        Execution(DropCaches, DropCaches.Param()),
        Execution(CPUGovernor, CPUGovernor.Param(cpu=CPU(3), governor="powersave")),
        Execution(CPUSetCreate, CPUSetCreate.Param(cpuset_name="/a")),
        Execution(CPUSetDelete, CPUSetDelete.Param(cpuset_name="/a")),
        Execution(CPUSetModify, CPUSetModify.Param(cpuset_name="/a", cpus=CPUNodeSet("2-3,8"),
                                                    mems=NUMANodeSet("0"))),
        Execution(CPUSetModify, CPUSetModify.Param(cpuset_name="/a", cpus=None, mems=None)),
        Execution(MoveTasks, MoveTasks.Param(cpuset_from="/a", cpuset_to="/b")),
        Execution(IRQAffinity, IRQAffinity.Param(irq=IRQ(12), operation=IRQAffinityOperation.mask,
                                                 cpus=CPUNodeSet("0-1"))),
        Execution(IRQAffinity, IRQAffinity.Param(irq=IRQ(12), operation=IRQAffinityOperation.add,
                                                 cpus=CPUNodeSet(""))),
    ]


def test_registry_names():
    assert set(ACTIONS) == {"cpuset-create", "cpuset-modify", "cpuset-delete", "move-tasks",
                            "irq-affinity", "cpu-governor", "drop-caches", "compact-memory"}
    for name, cls in ACTIONS.items():
        assert cls.name == name


@pytest.mark.parametrize("e", all_executions())
def test_roundtrip(e):
    d = json.loads(json.dumps(encode(e)))
    back = decode(d)
    assert back.action is e.action
    assert encode(back) == encode(e)
    assert type(back.params) is type(e.params)


def test_encoding_shape():
    e = Execution(IRQAffinity, IRQAffinity.Param(irq=IRQ(5), operation=IRQAffinityOperation.mask,
                                                 cpus=CPUNodeSet("0-1")))
    assert encode(e) == {"action": "irq-affinity",
                         "params": {"irq": 5, "operation": "mask", "cpus": "0-1"}}


def test_unknown_action_rejected():
    with pytest.raises(JournalError):
        decode({"action": "rm-rf", "params": {}})


def test_unknown_field_rejected():
    with pytest.raises(JournalError):
        decode({"action": "cpuset-create", "params": {"cpuset_name": "/a", "x": 1}})


def test_missing_field_rejected():
    with pytest.raises(JournalError):
        decode({"action": "cpuset-modify", "params": {"cpuset_name": "/a", "cpus": None}})


@pytest.mark.parametrize("params", [
    {"cpuset_name": 5},
    {"cpuset_name": ["x"]},
])
def test_wrong_type_rejected(params):
    with pytest.raises(JournalError):
        decode({"action": "cpuset-create", "params": params})


def test_bad_enum_and_nodeset_rejected():
    with pytest.raises(JournalError):
        decode({"action": "irq-affinity", "params": {"irq": 1, "operation": "bogus", "cpus": "0"}})
    with pytest.raises(JournalError):
        decode({"action": "irq-affinity", "params": {"irq": 1, "operation": "add", "cpus": "zz!"}})


# ---------------------------------------------------------------- file

def steps(name="/a"):
    return [Execution(CPUSetCreate, CPUSetCreate.Param(cpuset_name=name)),
            Execution(CPUSetDelete, CPUSetDelete.Param(cpuset_name=name))]


def write(path, content, mode=0o600):
    if isinstance(content, str):
        content = content.encode()
    path.write_bytes(content)
    os.chmod(path, mode)


def test_header_and_mode(tmp_path):
    p = tmp_path / "j"
    a = journal.open_for_append(str(p))
    a.close()
    assert p.read_text() == HEADER
    assert (p.stat().st_mode & 0o777) == 0o600
    assert journal.read_journal(str(p)) == []


def test_append_and_read(tmp_path):
    p = str(tmp_path / "j")
    a = journal.open_for_append(p)
    a.append(steps("/a"))
    a.append([])  # no record
    a.close()
    a = journal.open_for_append(p)
    a.append(steps("/b"))
    a.close()
    lines = open(p).read().splitlines()
    assert len(lines) == 3
    recs = journal.read_journal(p)
    assert [r[0].params.cpuset_name for r in recs] == ["/a", "/b"]
    assert recs[0][1].action is CPUSetDelete


def test_non_journal_rejected_untouched(tmp_path):
    p = tmp_path / "j"
    write(p, "hello world\n")
    with pytest.raises(JournalError):
        journal.open_for_append(str(p))
    with pytest.raises(JournalError):
        journal.read_journal(str(p))
    assert p.read_text() == "hello world\n"


def test_missing_file(tmp_path):
    p = str(tmp_path / "nope")
    with pytest.raises(JournalError, match="nope"):
        journal.read_journal(p)


def test_symlink_rejected(tmp_path):
    target = tmp_path / "t"
    link = tmp_path / "l"
    link.symlink_to(target)
    with pytest.raises(JournalError):
        journal.open_for_append(str(link))
    assert not target.exists()
    with pytest.raises(JournalError):
        journal.read_journal(str(link))
    write(target, HEADER)
    with pytest.raises(JournalError):
        journal.open_for_append(str(link))
    with pytest.raises(JournalError):
        journal.read_journal(str(link))
    assert target.read_text() == HEADER


def test_group_other_writable_rejected(tmp_path):
    p = tmp_path / "j"
    write(p, HEADER, 0o666)
    with pytest.raises(JournalError):
        journal.open_for_append(str(p))
    with pytest.raises(JournalError):
        journal.read_journal(str(p))
    assert p.read_text() == HEADER


def test_other_owner_rejected(tmp_path, monkeypatch):
    p = tmp_path / "j"
    write(p, HEADER)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(p).st_uid + 1)
    with pytest.raises(JournalError):
        journal.read_journal(str(p))
    with pytest.raises(JournalError):
        journal.open_for_append(str(p))


@pytest.mark.parametrize("first", [b"\x80", b"(", b"]"])
def test_pickle_rejected(tmp_path, first):
    p = tmp_path / "j"
    content = first + b"\x04\x95junk"
    write(p, content)
    for fn in (journal.read_journal, journal.open_for_append):
        with pytest.raises(JournalError, match="0.5.2"):
            fn(str(p))
    assert p.read_bytes() == content


def test_wrong_version_rejected(tmp_path):
    p = tmp_path / "j"
    write(p, '{"format": "vfio-isolate-undo", "version": 2}\n')
    with pytest.raises(JournalError):
        journal.read_journal(str(p))
    with pytest.raises(JournalError):
        journal.open_for_append(str(p))


def record(name):
    return json.dumps({"undo": [encode(steps(name)[0])]}) + "\n"


def test_truncated_last_line_dropped(tmp_path, capsys):
    p = tmp_path / "j"
    write(p, HEADER + record("/a") + '{"undo": [{"acti')
    recs = journal.read_journal(str(p))
    assert len(recs) == 1
    assert "truncated" in capsys.readouterr().err


def test_append_after_truncated_line(tmp_path):
    p = tmp_path / "j"
    write(p, HEADER + record("/a") + '{"undo": [{"acti')
    a = journal.open_for_append(str(p))
    a.append(steps("/b"))
    a.close()
    recs = journal.read_journal(str(p))
    assert [r[0].params.cpuset_name for r in recs] == ["/a", "/b"]


def test_corrupt_middle_line_rejected(tmp_path):
    p = tmp_path / "j"
    write(p, HEADER + record("/a") + "garbage\n" + record("/b"))
    with pytest.raises(JournalError):
        journal.read_journal(str(p))


def test_unknown_action_rejects_whole_file(tmp_path):
    p = tmp_path / "j"
    bad = json.dumps({"undo": [{"action": "evil", "params": {}}]}) + "\n"
    write(p, HEADER + record("/a") + bad + record("/b"))
    with pytest.raises(JournalError):
        journal.read_journal(str(p))


def test_rewrite(tmp_path):
    p = tmp_path / "j"
    a = journal.open_for_append(str(p))
    a.append(steps("/a"))
    a.close()
    journal.rewrite(str(p), [steps("/x")])
    assert (p.stat().st_mode & 0o777) == 0o600
    assert [r[0].params.cpuset_name for r in journal.read_journal(str(p))] == ["/x"]
    journal.rewrite(str(p), [])
    assert journal.read_journal(str(p)) == []
    assert os.listdir(tmp_path) == ["j"]


GOOD = '{"undo": [{"action": "cpuset-delete", "params": {"cpuset_name": "/a"}}]}\n'


@pytest.mark.parametrize("bad", [
    '{"undo": [{"action": "rm-rf", "params": {}}]}\n',
    '{"undo": 5}\n',
    'not json\n',
])
def test_bad_terminated_last_line_is_corruption(tmp_path, bad):
    p = tmp_path / "j"
    content = HEADER + GOOD + bad
    write(p, content)
    with pytest.raises(JournalError):
        journal.read_journal(str(p))
    with pytest.raises(JournalError):
        journal.open_for_append(str(p))
    assert p.read_text() == content


def test_appender_validates_all_records(tmp_path):
    for bad in ('{"undo": [{"action": "rm-rf", "params": {}}]}\n', 'garbage\n'):
        p = tmp_path / "j"
        content = HEADER + bad + GOOD
        write(p, content)
        with pytest.raises(JournalError):
            journal.open_for_append(str(p))
        assert p.read_text() == content


def test_unterminated_bad_last_line_tolerated(tmp_path, capsys):
    p = tmp_path / "j"
    write(p, HEADER + GOOD + '{"undo": [{"acti')
    assert len(journal.read_journal(str(p))) == 1
    assert "truncated" in capsys.readouterr().err
    journal.open_for_append(str(p)).close()
    assert p.read_text() == HEADER + GOOD


def test_bool_version_rejected(tmp_path):
    p = tmp_path / "j"
    write(p, '{"format": "vfio-isolate-undo", "version": true}\n')
    with pytest.raises(JournalError):
        journal.read_journal(str(p))
    with pytest.raises(JournalError):
        journal.open_for_append(str(p))


def test_fifo_rejected_without_blocking(tmp_path):
    p = tmp_path / "f"
    os.mkfifo(p, 0o600)
    with pytest.raises(JournalError):
        journal.read_journal(str(p))
    with pytest.raises(JournalError):
        journal.open_for_append(str(p))
