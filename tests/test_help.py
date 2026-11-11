from vfio_isolate import cli


def _help(capsys, *argv):
    assert cli.main(list(argv) + ["--help"]) == 0
    return capsys.readouterr().out


def test_cpuset_modify_help_documents_cpu_forms(capsys):
    out = _help(capsys, "cpuset-modify")
    for token in ("C<list>", "N<list>", "M<mask>"):
        assert token in out


def test_group_help_mentions_root_and_exit_statuses(capsys):
    out = _help(capsys)
    assert "root" in out
    assert "130" in out


def test_group_help_mentions_append(capsys):
    assert "appended" in _help(capsys)


def test_restore_help_mentions_deletion_and_failed_steps(capsys):
    out = " ".join(_help(capsys, "restore").split())
    assert "deleted on success" in out
    assert "failed steps are kept" in out


def test_cpu_forms_documented_in_commands(capsys):
    for cmd in ("irq-affinity", "cpu-governor", "cpuset-create"):
        assert "M<mask>" in _help(capsys, cmd)


def test_restore_help_mentions_newest_first(capsys):
    assert "newest first" in _help(capsys, "restore")


def test_hugepages_help(capsys):
    out = " ".join(_help(capsys, "hugepages").split())
    for token in ("<pagesize>", "<amount>", "--node", "N<n>", "<page size=", "releases", "no undo record"):
        assert token in out
