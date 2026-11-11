"""Indirection for /sys and /proc so tests can point the tool at a fake host tree."""

ROOT = "/"


def path(*parts: str) -> str:
    """Join parts onto ROOT. ROOT is read on every call; leading slashes of parts are stripped."""
    stripped = [p.lstrip("/") for p in parts]
    base = ROOT.rstrip("/")
    return base + "/" + "/".join(s for s in stripped if s)
