"""AST node classes. Every node records the source line it came from."""


class Node:
    fields = ()

    def __init__(self, *args, line=None):
        for name, value in zip(self.fields, args):
            setattr(self, name, value)
        self.line = line

    def __repr__(self):
        args = ", ".join(f"{f}={getattr(self, f)!r}" for f in self.fields)
        return f"{type(self).__name__}({args})"

    def __eq__(self, other):
        # Structural equality (ignores line) so tests can compare trees.
        return type(self) is type(other) and all(
            getattr(self, f) == getattr(other, f) for f in self.fields)


# ----- Program / statements -----
class Program(Node):
    fields = ("statements",)


class Assign(Node):
    fields = ("name", "value")


class Print(Node):
    fields = ("value",)


class If(Node):
    fields = ("condition", "then_body", "else_body")  # else_body may be None


class While(Node):
    fields = ("condition", "body")


class Block(Node):
    fields = ("statements",)


class For(Node):
    fields = ("init", "condition", "update", "body")  # init/condition/update may be None


class Break(Node):
    fields = ()


class Continue(Node):
    fields = ()


class FuncDef(Node):
    fields = ("name", "params", "body")  # params: list of names


class Return(Node):
    fields = ("value",)  # value may be None (returns 0)


class ExprStmt(Node):
    fields = ("expr",)  # a call used as a statement; its result is discarded


# ----- Expressions -----
class Number(Node):
    fields = ("value",)


class Var(Node):
    fields = ("name",)


class BinOp(Node):
    fields = ("op", "left", "right")  # + - * / == != < > <= >=


class LogicalOp(Node):
    fields = ("op", "left", "right")  # and / or (short-circuit)


class UnaryOp(Node):
    fields = ("op", "operand")  # - / not


class Call(Node):
    fields = ("name", "args")


def to_dict(node):
    """Convert an AST into plain dicts/lists (JSON-serialisable) for the web API."""
    if isinstance(node, list):
        return [to_dict(n) for n in node]
    if not isinstance(node, Node):
        return node
    result = {"type": type(node).__name__, "line": node.line}
    for f in node.fields:
        result[f] = to_dict(getattr(node, f))
    return result


def _is_child(value):
    """Sub-trees print on their own lines; plain values (names, params) stay inline."""
    return isinstance(value, Node) or (
        isinstance(value, list) and all(isinstance(v, Node) for v in value))


def dump(node, indent=0):
    """Return an indented, human-readable tree of the AST."""
    pad = "  " * indent
    if isinstance(node, list):
        return "\n".join(dump(n, indent) for n in node)
    if not isinstance(node, Node):
        return f"{pad}{node!r}"

    children = [f for f in node.fields if _is_child(getattr(node, f))]
    simple = [f for f in node.fields if f not in children]
    header = f"{pad}{type(node).__name__}"
    if simple:
        header += "(" + ", ".join(f"{f}={getattr(node, f)!r}" for f in simple) + ")"
    header += f"  [line {node.line}]"
    lines = [header]
    for f in children:
        lines.append(f"{pad}  {f}:")
        value = getattr(node, f)
        if isinstance(value, list) and not value:
            lines.append(f"{pad}    (empty)")
        else:
            lines.append(dump(value, indent + 2))
    return "\n".join(lines)
