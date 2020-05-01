from parsimonious.grammar import Grammar
from parsimonious.nodes import NodeVisitor


class _MaskVisitor(NodeVisitor):

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


class CPUMaskParser:
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
        return _MaskVisitor().visit(tree)


class CPUMask:

    base_path = "/sys/devices/system/cpu"
    _present = None
    _possible = None

    @classmethod
    def present(cls):
        if not cls._present:
            with open(cls.base_path + "/present") as f:
                cls._present = CPUMask(f.read())
        return cls._present

    @classmethod
    def possible(cls):
        if not cls._possible:
            with open(cls.base_path + "/possible") as f:
                cls._present = CPUMask(f.read())
        return cls._possible

    def __init__(self, initial=None):
        if not initial:
            self.cpus = set()
        elif isinstance(initial, str):
            self.cpus = CPUMaskParser.parse(initial)
        else:
            raise Exception("unable to initialize")

    def __repr__(self):
        return f"CPUMask {self.to_list_representation()}"

    def to_list_representation(self):
        nums = sorted(self.cpus)
        gaps = [[s, e] for s, e in zip(nums, nums[1:]) if s + 1 < e]
        edges = iter(nums[:1] + sum(gaps, []) + nums[-1:])
        segments = []
        for r in zip(edges, edges):
            if r[0] == r[1]:
                segments.append(str(r[0]))
            else:
                segments.append("{}-{}".format(r[0], r[1]))
        return ",".join(segments)


if __name__ == "__main__":
    print(CPUMask("00000001,0013f03f").to_list_representation())
    print(CPUMaskParser.parse("1,3"))
    print(CPUMask.present().cpus)
