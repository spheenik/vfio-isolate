"""README examples: parse every `sh` invocation, lint the blocks, check command coverage.

Heuristic by design: only blocks fenced as ```sh are looked at; simple NAME=value
assignments are substituted (see readme_examples.py). Execution is patched out, so only
parsing/validation is checked.
"""
import re
from pathlib import Path


from readme_examples import extract, logical_lines, sh_blocks
from vfio_isolate import cli, journal

README = Path(__file__).resolve().parent.parent / "README.md"

def _text():
    return README.read_text()


def _rewrite_paths(argv, tmp_path):
    """Redirect -u/--undo-file values and restore's argument into tmp_path; returns the
    list of journal files restore needs to find."""
    argv = list(argv)
    need = []
    i = 0
    while i < len(argv):
        if argv[i] in ("-u", "--undo-file") and i + 1 < len(argv):
            argv[i + 1] = str(tmp_path / "undo" / Path(argv[i + 1]).name)
            i += 1
        elif argv[i] == "restore" and i + 1 < len(argv):
            # restore [-n] FILE: FILE is the last argument
            argv[-1] = str(tmp_path / "undo" / Path(argv[-1]).name)
            need.append(argv[-1])
            i = len(argv)
        i += 1
    return argv, need


def test_readme_invocations_parse(fake_host_factory, monkeypatch, tmp_path):
    fake_host_factory(num_cpus=32, governors="performance powersave")
    monkeypatch.setattr(cli.Executor, "run", lambda self: 0)
    (tmp_path / "undo").mkdir()
    invocations = extract(_text())
    assert len(invocations) >= 5, f"only {len(invocations)} vfio-isolate invocations found in sh blocks"
    for no, argv in invocations:
        assert not any("$" in a for a in argv), f"README.md:{no}: unsubstituted variable in {argv}"
        argv, need = _rewrite_paths(argv, tmp_path)
        for f in need:
            journal.rewrite(f, [])
        assert cli.main(argv) == 0, f"README.md:{no}: {argv}"


def test_readme_lint():
    problems = []
    blocks = sh_blocks(_text())
    assert blocks, "no sh blocks in README.md"
    for _start, lines in blocks:
        for no, line in lines:
            if re.search(r"\\\s+$", line):
                problems.append(f"README.md:{no}: backslash followed by whitespace")
            if re.match(r"^\s*[#$]\s*(sudo|vfio-isolate)\b", line):
                problems.append(f"README.md:{no}: prompt prefix")
    assert not problems, "\n".join(problems)


def test_readme_covers_every_command():
    headings = set(re.findall(r"^### (\S+)\s*$", _text(), re.M))
    missing = sorted(set(cli.cli.commands) - headings)
    assert not missing, f"no '### <command>' heading for: {missing}"


SYNTHETIC = """\
Intro
```sh
HCPUS=C0-3
MCPUS="C8-15"
VM=win10
UNDO=/run/x-$VM.undo
# comment
sudo vfio-isolate -u /run/x.undo \\
    drop-caches \\
    cpu-governor performance ${MCPUS}
vfio-isolate restore $UNDO
```
```xml
<x>vfio-isolate nope</x>
```
```sh
prepare() {
    vfio-isolate cpuset-modify --cpus $HCPUS /system.slice
}
vfio-isolate restore /run/x.undo
```
```sh
if ! vfio-isolate restore /run/a.undo; then
    echo failed
fi
if sudo vfio-isolate drop-caches; then
    :
fi
! vfio-isolate compact-memory
```
"""


def test_extract_synthetic():
    assert extract(SYNTHETIC) == [
        (8, ["-u", "/run/x.undo", "drop-caches", "cpu-governor", "performance", "C8-15"]),
        (11, ["restore", "/run/x-win10.undo"]),
        (18, ["cpuset-modify", "--cpus", "$HCPUS", "/system.slice"]),
        (20, ["restore", "/run/x.undo"]),
        (23, ["restore", "/run/a.undo"]),
        (26, ["drop-caches"]),
        (29, ["compact-memory"]),
    ]
