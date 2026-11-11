"""Undo journal: JSON codec for undo steps and the journal file functions.

The journal is JSON Lines. Line 1 is a header, every further line is one record
`{"undo": [step, ...]}` holding one action's undo steps in apply order. Only known
actions and known parameter types can be decoded, so reading a journal never runs
arbitrary code.
"""
import dataclasses
import fcntl
import json
import os
import stat
import sys
import typing
from enum import Enum

from vfio_isolate.action import ACTIONS, Execution
from vfio_isolate.irq import IRQ
from vfio_isolate.cpu import CPU
from vfio_isolate.nodeset import CPUNodeSet, NUMANodeSet

FORMAT = "vfio-isolate-undo"
VERSION = 1
HEADER = {"format": FORMAT, "version": VERSION}

__all__ = ['JournalError', 'encode', 'decode', 'open_for_append', 'read_journal', 'rewrite']


class JournalError(Exception):
    pass


# ---------------------------------------------------------------- codec

def _param_types(cls) -> dict:
    return typing.get_type_hints(cls.Param)


def _unwrap_optional(t):
    """Return X for Optional[X], else None."""
    if typing.get_origin(t) is typing.Union:
        args = [a for a in typing.get_args(t) if a is not type(None)]
        if len(args) == 1 and len(typing.get_args(t)) == 2:
            return args[0]
    return None


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _encode_value(value, t, field):
    inner = _unwrap_optional(t)
    if inner is not None:
        return None if value is None else _encode_value(value, inner, field)
    if t == typing.List[int]:
        if isinstance(value, list) and all(_is_int(v) for v in value):
            return list(value)
        return _bad(field, value)
    if value is None:
        return None
    if t is str:
        ok = isinstance(value, str)
        return value if ok else _bad(field, value)
    if t is bool:
        return value if isinstance(value, bool) else _bad(field, value)
    if t is int:
        return value if isinstance(value, int) and not isinstance(value, bool) else _bad(field, value)
    if t in (CPUNodeSet, NUMANodeSet):
        return value.to_list_form() if isinstance(value, t) else _bad(field, value)
    if t in (IRQ, CPU):
        return value.number if isinstance(value, t) else _bad(field, value)
    if isinstance(t, type) and issubclass(t, Enum):
        return value.name if isinstance(value, t) else _bad(field, value)
    raise JournalError(f"unsupported parameter type {t} for field '{field}'")


def _bad(field, value):
    raise JournalError(f"invalid value {value!r} for field '{field}'")


def _decode_value(value, t, field):
    inner = _unwrap_optional(t)
    if inner is not None:
        return None if value is None else _decode_value(value, inner, field)
    if t == typing.List[int]:
        if isinstance(value, list) and all(_is_int(v) for v in value):
            return list(value)
        _bad(field, value)
    if value is None:
        return None
    if t is str:
        if isinstance(value, str):
            return value
    elif t is bool:
        if isinstance(value, bool):
            return value
    elif t is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif t in (CPUNodeSet, NUMANodeSet):
        if isinstance(value, str):
            try:
                return t(value)
            except Exception:
                _bad(field, value)
    elif t in (IRQ, CPU):
        if isinstance(value, int) and not isinstance(value, bool):
            return t(value)
    elif isinstance(t, type) and issubclass(t, Enum):
        if isinstance(value, str) and value in t.__members__:
            return t[value]
    else:
        raise JournalError(f"unsupported parameter type {t} for field '{field}'")
    _bad(field, value)


def encode(execution: Execution) -> dict:
    cls = execution.action
    if getattr(cls, "name", None) is None or ACTIONS.get(cls.name) is not cls:
        raise JournalError(f"unknown action {cls!r}")
    types = _param_types(cls)
    params = {}
    for f in dataclasses.fields(cls.Param):
        params[f.name] = _encode_value(getattr(execution.params, f.name), types[f.name], f.name)
    return {"action": cls.name, "params": params}


def decode(d) -> Execution:
    if not isinstance(d, dict) or set(d) != {"action", "params"}:
        raise JournalError(f"malformed undo step: {d!r}")
    name = d["action"]
    cls = ACTIONS.get(name) if isinstance(name, str) else None
    if cls is None:
        raise JournalError(f"unknown action {name!r}")
    raw = d["params"]
    if not isinstance(raw, dict):
        raise JournalError(f"malformed params for action '{name}'")
    types = _param_types(cls)
    unknown = set(raw) - set(types)
    if unknown:
        raise JournalError(f"unknown field(s) for action '{name}': {', '.join(sorted(unknown))}")
    defaults = {}
    for f in dataclasses.fields(cls.Param):
        if f.default is not dataclasses.MISSING:
            defaults[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:
            defaults[f.name] = f.default_factory()
    missing = set(types) - set(raw) - set(defaults)
    if missing:
        raise JournalError(f"missing field(s) for action '{name}': {', '.join(sorted(missing))}")
    kwargs = {k: _decode_value(raw[k], types[k], k) if k in raw else defaults[k] for k in types}
    return Execution(cls, cls.Param(**kwargs))


# ---------------------------------------------------------------- file

def _open_fd(path, flags, mode=0o600):
    try:
        return os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, mode)
    except FileNotFoundError:
        raise JournalError(f"undo file {path} does not exist")
    except OSError as e:
        raise JournalError(f"cannot open undo file {path}: {e.strerror}")


def _check_fd(fd, path):
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise JournalError(f"undo file {path} is not a regular file")
    if st.st_uid != os.geteuid():
        raise JournalError(f"undo file {path} is not owned by the current user")
    if st.st_mode & 0o022:
        raise JournalError(f"undo file {path} is writable by group or others")
    # opened O_NONBLOCK so special files cannot block; regular files need no such flag
    fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
    return st


def _fsync_dir(path):
    directory = os.path.dirname(os.path.abspath(path))
    dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _read_all(fd) -> bytes:
    chunks = []
    while True:
        c = os.read(fd, 1 << 20)
        if not c:
            break
        chunks.append(c)
    return b"".join(chunks)


def _check_header(data: bytes, path):
    """Validate the header line at the start of data; return the offset after it."""
    if data[:1] in (b"\x80", b"(", b"]"):
        raise JournalError(
            f"undo file {path} was written by vfio-isolate 0.5.x; "
            f"restore it with vfio-isolate 0.5.2")
    nl = data.find(b"\n")
    if nl < 0:
        raise JournalError(f"{path} is not a vfio-isolate undo journal")
    try:
        header = json.loads(data[:nl].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise JournalError(f"{path} is not a vfio-isolate undo journal")
    if not isinstance(header, dict) or header.get("format") != FORMAT:
        raise JournalError(f"{path} is not a vfio-isolate undo journal")
    if type(header.get("version")) is not int or header["version"] != VERSION:
        raise JournalError(f"{path}: unsupported undo journal version {header.get('version')!r}")
    return nl + 1


def _parse_line(line: bytes):
    obj = json.loads(line.decode("utf-8"))
    if not isinstance(obj, dict) or set(obj) != {"undo"} or not isinstance(obj["undo"], list):
        raise ValueError("bad record")
    return [decode(s) for s in obj["undo"]]


def _parse_records(data: bytes, start: int, path):
    """Parse and decode every record after the header.

    Returns (records, tail, tail_start). Every newline-terminated line must be a valid
    record, otherwise JournalError. A last line without terminating newline is a possible
    crash truncation: tail is "complete" if it is a valid record (kept), "truncated" if it
    is not valid JSON/shape (dropped), else None; tail_start is its offset in data.
    """
    lines = data[start:].split(b"\n")
    tail = lines.pop()
    records = []
    for i, line in enumerate(lines):
        try:
            records.append(_parse_line(line))
        except (ValueError, UnicodeDecodeError):
            raise JournalError(f"{path}: corrupt journal at record {i + 1}")
    if not tail:
        return records, None, len(data)
    tail_start = len(data) - len(tail)
    try:
        records.append(_parse_line(tail))
    except (ValueError, UnicodeDecodeError):
        return records, "truncated", tail_start
    return records, "complete", tail_start


class _Appender:
    def __init__(self, fd):
        self._fd = fd
        self._last = None  # offset before the last non-empty append, None if nothing to discard

    def append(self, steps):
        steps = list(steps)
        self._last = None
        if not steps:
            return
        line = json.dumps({"undo": [encode(s) for s in steps]}) + "\n"
        offset = os.fstat(self._fd).st_size
        _write_all(self._fd, line.encode("utf-8"))
        os.fsync(self._fd)
        self._last = offset

    def discard_last(self):
        """Remove the record written by the last append(); no-op if there is none."""
        if self._last is None:
            return
        os.ftruncate(self._fd, self._last)
        os.fsync(self._fd)
        self._last = None

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _write_all(fd, data: bytes):
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def open_for_append(path) -> _Appender:
    fd = _open_fd(path, os.O_RDWR | os.O_CREAT | os.O_APPEND)
    try:
        st = _check_fd(fd, path)
        if st.st_size == 0:
            _write_all(fd, (json.dumps(HEADER) + "\n").encode("utf-8"))
            os.fsync(fd)
            _fsync_dir(path)
        else:
            os.lseek(fd, 0, os.SEEK_SET)
            data = _read_all(fd)
            start = _check_header(data, path)
            _, tail, tail_start = _parse_records(data, start, path)
            if tail == "complete":
                _write_all(fd, b"\n")
                os.fsync(fd)
            elif tail == "truncated":
                print(f"warning: {path}: dropping truncated last line", file=sys.stderr)
                os.ftruncate(fd, tail_start)
                os.fsync(fd)
        return _Appender(fd)
    except BaseException:
        os.close(fd)
        raise


def read_journal(path) -> list:
    fd = _open_fd(path, os.O_RDONLY)
    try:
        _check_fd(fd, path)
        data = _read_all(fd)
    finally:
        os.close(fd)
    start = _check_header(data, path)
    records, tail, _ = _parse_records(data, start, path)
    if tail == "truncated":
        print(f"warning: {path}: ignoring truncated last line", file=sys.stderr)
    return records


def rewrite(path, records):
    """Atomically replace the journal with header + records (list of lists of Execution)."""
    directory = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    content = json.dumps(HEADER) + "\n" + "".join(
        json.dumps({"undo": [encode(s) for s in r]}) + "\n" for r in records)
    for attempt in range(100):
        tmp = os.path.join(directory, f".{base}.{os.getpid()}.{attempt}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            break
        except FileExistsError:
            continue
    else:
        raise JournalError(f"cannot create temporary file next to {path}")
    try:
        try:
            _write_all(fd, content.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
        _fsync_dir(path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
