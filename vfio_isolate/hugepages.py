"""Hugepage pools under /sys (system-wide and per NUMA node)."""
import os
import re
from typing import List, Optional

from vfio_isolate import fsroot

_DIR_RE = re.compile(r"^hugepages-(\d+)kB$")
_SIZE_RE = re.compile(r"^(\d+)\s*([KMG])(?:B)?$", re.IGNORECASE)
_UNITS = {"K": 1, "M": 1024, "G": 1024 * 1024}


def pool_dir(size_kb: int, node: Optional[int] = None) -> str:
    sub = f"hugepages/hugepages-{size_kb}kB"
    if node is None:
        return fsroot.path("/sys/kernel/mm", sub)
    return fsroot.path(f"/sys/devices/system/node/node{node}", sub)


def read_count(size_kb: int, node: Optional[int] = None) -> int:
    with open(os.path.join(pool_dir(size_kb, node), "nr_hugepages")) as f:
        return int(f.read().strip())


def write_count(size_kb: int, node: Optional[int], count: int):
    with open(os.path.join(pool_dir(size_kb, node), "nr_hugepages"), "w") as f:
        f.write(str(count))


def available_sizes() -> List[int]:
    """Sizes in kB the kernel offers, ascending."""
    try:
        names = os.listdir(fsroot.path("/sys/kernel/mm/hugepages"))
    except OSError:
        return []
    sizes = []
    for n in names:
        m = _DIR_RE.match(n)
        if m:
            sizes.append(int(m.group(1)))
    return sorted(sizes)


def parse_size(text: str) -> int:
    """'2M', '2048k', '2048KB', '1g' -> kB. Raises ValueError."""
    m = _SIZE_RE.match(text.strip())
    if not m:
        raise ValueError(f"{text!r}: not a size; use <n>K, <n>M or <n>G, for example 2M or 1G")
    kb = int(m.group(1)) * _UNITS[m.group(2).upper()]
    if kb <= 0:
        raise ValueError(f"{text!r}: the size must be positive")
    return kb


def format_size(size_kb: int) -> str:
    """The largest exact unit: 6G, 512M, 4096K is only used if not a whole M."""
    for suffix, unit in (("G", 1024 * 1024), ("M", 1024)):
        if size_kb % unit == 0:
            return f"{size_kb // unit}{suffix}"
    return f"{size_kb}K"
