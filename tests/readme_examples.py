"""Extract `vfio-isolate` invocations from the README's `sh` code blocks.

Convention (see openspec/changes/readme-and-tests): shell blocks are fenced as ```sh;
a command is a line starting with `vfio-isolate` (optionally after `sudo `, optionally
indented inside a shell function); `\\` continuations are joined; `NAME=value` lines in
the same block are substituted for `$NAME` / `${NAME}` (values may refer to variables
assigned earlier in the block).
"""
import re
import shlex
from typing import List, Tuple

_FENCE = re.compile(r"^(\s*)```\s*(\S*)\s*$")
_ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_CMD = re.compile(r"^\s*(?:(?:if\s+)?!?\s*)?(?:sudo\s+)?vfio-isolate(\s|$)")
_LEAD = re.compile(r"^\s*(?:if\s+)?(?:!\s*)?")
_TRAIL = re.compile(r";\s*then\s*$")
_VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def sh_blocks(text: str) -> List[Tuple[int, List[Tuple[int, str]]]]:
    """[(first line number, [(line number, line), ...]), ...] for each ```sh block."""
    blocks, cur, start, lang = [], None, 0, None
    for no, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if m and cur is None:
            lang, cur, start = m.group(2), [], no + 1
        elif m and cur is not None:
            if lang == "sh":
                blocks.append((start, cur))
            cur = None
        elif cur is not None:
            cur.append((no, line))
    return blocks


def logical_lines(lines):
    """Join `\\` continuations; yields (line number of first physical line, text)."""
    out, buf, first = [], None, 0
    for no, line in lines:
        if buf is None:
            buf, first = line, no
        else:
            buf += " " + line.strip()
        if buf.endswith("\\"):
            buf = buf[:-1].rstrip()
            continue
        out.append((first, buf))
        buf = None
    if buf is not None:
        out.append((first, buf))
    return out


def _unquote(value: str) -> str:
    value = value.strip()
    try:
        parts = shlex.split(value, comments=True)
    except ValueError:
        return value
    return parts[0] if len(parts) == 1 else value


def extract(text: str) -> List[Tuple[int, List[str]]]:
    """Return [(line number, argv)] for every vfio-isolate invocation (argv without the
    program name). Variables still containing `$` after substitution are left in the
    argv, so callers can fail on them."""
    result = []
    for _start, lines in sh_blocks(text):
        env = {}
        for no, line in logical_lines(lines):
            m = _ASSIGN.match(line)
            if m:
                value = _unquote(m.group(2))
                env[m.group(1)] = _VAR.sub(lambda v: env.get(v.group(1) or v.group(2), v.group(0)), value)
                continue
            if not _CMD.match(line):
                continue
            line = _VAR.sub(lambda v: env.get(v.group(1) or v.group(2), v.group(0)), line)
            line = _TRAIL.sub("", _LEAD.sub("", line, count=1))
            argv = shlex.split(line, comments=True)
            if argv[0] == "sudo":
                argv = argv[1:]
            result.append((no, argv[1:]))
    return result
