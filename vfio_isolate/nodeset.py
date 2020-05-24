import os

from parsimonious.grammar import Grammar
from parsimonious.nodes import NodeVisitor


class _NodeSetVisitor(NodeVisitor):

    def visit_sentence(self, _, children):
        return children[0]

    def visit_list_form(self, _, children):
        value = children[0]
        for item in children[1]:
            value = value.union(item[1])
        return value

    def visit_list_entry(self, _, children):
        v = children[0]
        if isinstance(v, int):
            return {v}
        elif isinstance(v, range):
            return set(v)
        else:
            raise Exception("don't know how to handle")

    def visit_mask_form(self, _, children):
        values = [children[0]]
        for item in children[1]:
            values.insert(0, item[1])
        bit = 0
        result = set()
        for value in values:
            for n in range(32):
                if value & 1:
                    result.add(bit)
                value = value >> 1
                bit = bit + 1
        return result

    def visit_mask_entry(self, value, _):
        return int(value.text, 16)

    def visit_range(self, _, children):
        low, _, high = children
        return range(low, high + 1)

    def visit_number(self, number, _):
        return int(number.text)

    def generic_visit(self, node, children):
        return children or node


class NodeSetParser:
    grammar = Grammar(
        """
        sentence      = (mask_form / list_form)
        list_form     = list_entry (comma list_entry)* 
        list_entry    = (range / number)
        mask_form     = mask_entry (comma mask_entry)*
        mask_entry    = ~"[0-9a-f]{8}"
        range         = number minus number
        number        = ~"(0|[1-9][0-9]*)"
        comma         = ","
        minus         = "-"
        """)

    @classmethod
    def parse(cls, string_representation):
        tree = cls.grammar.parse(string_representation.strip())
        return _NodeSetVisitor().visit(tree)


class NodeSet:

    def __init__(self, initial=None):
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

    def possible(self):
        raise Exception("must properly override")

    def negation(self):
        return self.__class__({cpu for cpu in self.possible() if cpu not in self.nodes})

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
        return f"/sys/devices/system/cpu/cpu{node}{path}"

    def possible(self):
        from vfio_isolate.system import possible_cpus
        return possible_cpus()

    def is_valid(self):
        for node in self:
            if not os.path.exists(self.__cpu_path(node)):
                return False
        return True


class NUMANodeSet(NodeSet):

    @staticmethod
    def __node_path(node, path=""):
        return f"/sys/devices/system/node/node{node}{path}"

    def is_valid(self):
        for node in self:
            if not os.path.exists(self.__node_path(node)):
                return False
        return True

    def possible(self):
        from vfio_isolate.system import possible_nodes
        return possible_nodes()

    def get_cpu_nodeset(self):
        cpus = CPUNodeSet()
        for node in self:
            with open(self.__node_path(node, "/cpulist")) as f:
                cpus = cpus.union(CPUNodeSet(f.read()))
        return cpus


if __name__ == "__main__":
    print(NUMANodeSet("0").negation().get_cpu_nodeset().negation())
