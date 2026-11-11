import os

from vfio_isolate import fsroot
import re

from vfio_isolate.nodeset_parser import Transformer, Lark_StandAlone, LarkError, VisitError

def _base_path():
    return fsroot.path("/sys/devices/system")

def cache(func):
    def wrapper():
        if not wrapper.value:
            wrapper.value = func()
        return wrapper.value

    wrapper.value = None
    return wrapper


# Upper bound for a range endpoint. Linux allows at most 8192 CPUs (NR_CPUS) and 1024 NUMA
# nodes, so kernel cpulist/online files never come near this; it only stops absurd user input
# like C0-99999999999 from building a huge set before the existence checks.
MAX_RANGE_END = 65535


class NodeSetSyntaxError(ValueError):
    """A nodeset string that cannot be parsed."""


class _LarkTransformer(Transformer):

    def list_form(self, children):
        value = set()
        for item in children:
            value = value.union(item)
        return value

    def list_entry(self, children):
        v = children[0]
        if isinstance(v, str):
            return {int(v)}
        elif isinstance(v, range):
            return set(v)
        else:
            raise Exception("don't know how to handle")


    def range(self, children):
        low, high = int(children[0].value), int(children[1].value)
        if low > high:
            raise NodeSetSyntaxError(f"reversed range {low}-{high}")
        if high > MAX_RANGE_END:
            raise NodeSetSyntaxError(f"range too large {low}-{high}")
        return range(low, high + 1)


class NodeSetParser:
    @classmethod
    def parse(cls, string_representation):
        parser = Lark_StandAlone(transformer=_LarkTransformer())
        try:
            return parser.parse(string_representation)
        except VisitError as e:
            if isinstance(e.orig_exc, NodeSetSyntaxError):
                raise NodeSetSyntaxError(f"invalid nodeset {string_representation!r}: {e.orig_exc}") from None
            raise
        except LarkError as e:
            raise NodeSetSyntaxError(f"invalid nodeset {string_representation!r}") from e


class NodeSet:

    def __init__(self, initial=None):
        if isinstance(initial, str):
            initial = initial.rstrip()
        if not initial:
            self.nodes = set()
        elif isinstance(initial, set):
            self.nodes = initial
        elif isinstance(initial, str):
            self.nodes = NodeSetParser.parse(initial)
        else:
            raise Exception("unable to initialize NodeSet")

    def __repr__(self):
        return f"{self.__class__.__name__} {self.to_list_form()}"

    def __iter__(self):
        return iter(self.nodes)

    def __len__(self):
        return len(self.nodes)

    def __bool__(self):
        return len(self.nodes) != 0

    def __eq__(self, other):
        if isinstance(other, NodeSet):
            return self.nodes == other.nodes
        return False

    def negation(self):
        return self.__class__({n for n in self.universe() if n not in self.nodes})

    def union(self, other):
        return self.__class__(self.nodes.union(other.nodes))

    def intersection(self, other):
        return self.__class__(self.nodes.intersection(other.nodes))

    def to_list_form(self):
        nums = sorted(self.nodes)
        gaps = [[s, e] for s, e in zip(nums, nums[1:]) if s + 1 < e]
        edges = iter(nums[:1] + sum(gaps, []) + nums[-1:])
        segments = []
        for r in zip(edges, edges):
            if r[0] == r[1]:
                segments.append(str(r[0]))
            else:
                segments.append("{}-{}".format(r[0], r[1]))
        return ",".join(segments)


class CPUNodeSet(NodeSet):

    @staticmethod
    def __cpu_path(node, path=""):
        return fsroot.path(f"/sys/devices/system/cpu/cpu{node}{path}")

    @staticmethod
    @cache
    def present_cpus():
        with open(f"{_base_path()}/cpu/present") as f:
            return CPUNodeSet(f.read())

    @staticmethod
    @cache
    def possible_cpus():
        with open(f"{_base_path()}/cpu/possible") as f:
            return CPUNodeSet(f.read())

    @classmethod
    def universe(cls):
        return cls.possible_cpus()

    @classmethod
    def from_mask(cls, string_representation):
        s = string_representation.strip()
        if not re.fullmatch(r"[0-9a-f]{1,8}(,[0-9a-f]{1,8})*", s, re.IGNORECASE):
            raise NodeSetSyntaxError(f"invalid CPU mask {string_representation!r}")
        result = set()
        bit = 0
        for group in reversed(s.split(",")):
            value = int(group, 16)
            for _ in range(32):
                if value & 1:
                    result.add(bit)
                value >>= 1
                bit += 1
        return cls(result)

    def is_valid(self):
        for node in self:
            if not os.path.exists(self.__cpu_path(node)):
                return False
        return True


class NUMANodeSet(NodeSet):

    @staticmethod
    def __node_path(node, path=""):
        return fsroot.path(f"/sys/devices/system/node/node{node}{path}")

    @staticmethod
    @cache
    def online_nodes():
        with open(f"{_base_path()}/node/online") as f:
            return NUMANodeSet(f.read())

    @staticmethod
    @cache
    def possible_nodes():
        with open(f"{_base_path()}/node/possible") as f:
            return NUMANodeSet(f.read())

    @classmethod
    def universe(cls):
        return cls.possible_nodes()

    def is_valid(self):
        for node in self:
            if not os.path.exists(self.__node_path(node)):
                return False
        return True

    def get_cpu_nodeset(self):
        cpus = CPUNodeSet()
        for node in self:
            with open(self.__node_path(node, "/cpulist")) as f:
                cpus = cpus.union(CPUNodeSet(f.read()))
        return cpus
