"""Type checking: static type inference for MiniLang's two kinds of value, numbers and lists.

MiniLang has no type annotations and stays dynamically typed: a variable may hold a
number now and a list later. So the checker *infers* the set of types each variable
may hold at each point, and rejects an operation only when its operand's type is
*certain* to be wrong: always a list where a number is needed (`a + 1`, `if a`), or
always a number where a list is needed (`n[0]`, `len(n)`). Such a line would fail
every time it runs, so the checker reports it before anything runs, with every other
type error in the file. When a value could be either type, the check is left to the
VM at runtime, so a correct program is never rejected.

It is a forward data-flow analysis over the control-flow graph from ir.py, like
constant propagation, with sets of types as the lattice:

             {number, list}        could be either: no error is reported
              /          \\
        {number}        {list}
              \\          /
                   {}              no value reaches here

The meet where paths join is the union: after `if c { x = 1; } else { x = [1]; }`,
x is {number, list}. An assignment replaces a variable's type (a strong update).

It is also interprocedural. A parameter's type is the union of the argument types
at every call site, a call's type is the union of what the function returns, and a
global read inside a function may hold any type the program ever gives it. Every
value put into any list (a list literal, append, a[i] = v) is collected into one
element type, which is what a[i] reads. These all feed each other, so the whole
program is analysed again until nothing changes; only then are the checks made.
"""

from errors import TypeCheckError, raise_all
from ir import Const, Name, build_ir

NUMBER, LIST = "number", "list"
NUM = frozenset({NUMBER})
LST = frozenset({LIST})
ANY = NUM | LST
NOTHING = frozenset()

UNKNOWN = object()   # an input whose value isn't known, only its name


def show(types):
    return {NUM: "number", LST: "list", ANY: "number or list"}.get(types, "no value")


def type_of_value(value):
    return LST if isinstance(value, list) else NUM


def element_types(value):
    """Every type stored inside a list value, at any depth."""
    found = NOTHING
    if isinstance(value, list):
        for item in value:
            found |= type_of_value(item) | element_types(item)
    return found


def join(a, b):
    """Union of two states (variable -> types). A variable missing on one path has no value there."""
    if a is None:
        return dict(b)
    merged = dict(a)
    for name, types in b.items():
        merged[name] = merged.get(name, NOTHING) | types
    return merged


class Types:
    """What the checker inferred, for the symbol table and the playground."""

    def __init__(self, checker):
        self.globals = checker.globals
        self.functions = {}
        for name, proc in checker.functions.items():
            params = checker.params[name] if name in checker.called else [ANY] * len(proc.params)
            self.functions[name] = {"params": dict(zip(proc.params, params)),
                                    "returns": checker.returns[name],
                                    "locals": checker.locals[name]}
        self.elements = checker.elements

    def signature(self, name):
        fn = self.functions[name]
        params = ", ".join(f"{p}: {show(t)}" for p, t in fn["params"].items())
        return f"{name}({params}) -> {show(fn['returns'])}"

    def to_dict(self):
        return {
            "globals": {name: show(t) for name, t in sorted(self.globals.items())},
            "functions": {name: {"params": {p: show(t) for p, t in fn["params"].items()},
                                 "returns": show(fn["returns"]),
                                 "locals": {n: show(t) for n, t in sorted(fn["locals"].items())},
                                 "signature": self.signature(name)}
                          for name, fn in self.functions.items()},
            "elements": show(self.elements),
        }

    def format(self):
        """Plain text for main.py --debug."""
        lines = ["globals:"]
        lines += [f"  {name:<14}{show(t)}" for name, t in sorted(self.globals.items())] or ["  (none)"]
        for name, fn in self.functions.items():
            lines.append(f"function {self.signature(name)}")
            lines += [f"  {n:<14}{show(t)}" for n, t in sorted(fn["locals"].items()) if n not in fn["params"]]
        lines.append(f"list elements: {show(self.elements)}")
        return "\n".join(lines)


def check_types(program, inputs=()):
    """Infer types and check every operation. Returns Types, or raises TypeCheckError.

    inputs: the variables that exist before the program starts, as {name: value}
    (a level's test data), or just their names if the values aren't known.
    """
    return Checker(program, inputs).run()


class Checker:
    def __init__(self, program, inputs):
        self.ir = build_ir(program)
        self.main = self.ir.procedures[0]
        self.functions = {p.name.split("(")[0]: p for p in self.ir.procedures[1:]}
        if not isinstance(inputs, dict):
            inputs = {name: UNKNOWN for name in inputs}
        self.inputs, self.elements = {}, NOTHING
        for name, value in inputs.items():
            self.inputs[name] = ANY if value is UNKNOWN else type_of_value(value)
            self.elements |= ANY if value is UNKNOWN else element_types(value)
        self.globals = dict(self.inputs)          # every type each global is ever given
        self.params = {f: [NOTHING] * len(p.params) for f, p in self.functions.items()}
        self.returns = {f: NOTHING for f in self.functions}
        self.locals = {f: {} for f in self.functions}
        self.called = {q.target for p in self.ir.procedures for q in p.quads if q.op == "call"}
        self.entry = {}                           # proc name -> {block id: state on entry}
        self.errors = []

    def run(self):
        # Interprocedural fixed point: everything only grows, so this terminates.
        while True:
            before = self.summary()
            for proc in self.ir.procedures:
                self.entry[proc.name] = self.flow(proc)
                self.collect(proc)
            if self.summary() == before:
                break
        for proc in self.ir.procedures:
            self.walk(proc, self.check)
        if self.errors:
            raise_all(self.errors)
        return Types(self)

    def summary(self):
        return (dict(self.globals), {f: tuple(p) for f, p in self.params.items()}, dict(self.returns),
                self.elements, {f: dict(l) for f, l in self.locals.items()})

    # ------------------------------------------------------------ the data-flow analysis

    def start(self, proc):
        if proc is self.main:
            return dict(self.inputs)
        name = proc.name.split("(")[0]
        # A function nothing calls could be given anything: assume either type.
        params = self.params[name] if name in self.called else [ANY] * len(proc.params)
        return dict(zip(proc.params, params))

    def flow(self, proc):
        """Types on entry to each block of one procedure ({block id: state}, None = unreachable)."""
        blocks = proc.blocks
        entry = {b.id: None for b in blocks}
        out = {b.id: None for b in blocks}
        changed = True
        while changed:
            changed = False
            for block in blocks:
                incoming = self.start(proc) if block is blocks[0] else None
                for p in block.pred:
                    if out[p] is not None:
                        incoming = join(incoming, out[p])
                if incoming is None:
                    continue
                state = incoming
                for quad in block.quads:
                    state = self.transfer(proc, quad, state)
                if incoming != entry[block.id] or state != out[block.id]:
                    entry[block.id], out[block.id] = incoming, state
                    changed = True
        return entry

    def type_of(self, proc, arg, state):
        if isinstance(arg, Const):
            return NUM
        types = state.get(arg.name, NOTHING)
        if proc is not self.main and isinstance(arg, Name) and id(arg.node) not in self.ir.safe_reads:
            types |= self.globals.get(arg.name, NOTHING)   # the local may be unset: then the global is read
        return types

    def result(self, proc, quad, state):
        """The type of the value a quad writes (if it doesn't fail)."""
        if quad.op == "copy":
            return self.type_of(proc, quad.args[0], state)
        if quad.op == "list":
            return LST
        if quad.op == "index":
            return self.elements
        if quad.op == "call":
            return self.returns[quad.target]
        return NUM   # arithmetic, comparisons, not, len, append, input

    def transfer(self, proc, quad, state):
        if quad.dst is None:
            return state
        state = dict(state)
        state[quad.dst.name] = self.result(proc, quad, state)
        return state

    def walk(self, proc, visit):
        """Call visit(proc, quad, types of its operands, state) for every reachable quad."""
        for block in proc.blocks:
            state = self.entry[proc.name][block.id]
            if state is None:
                continue
            for quad in block.quads:
                visit(proc, quad, [self.type_of(proc, a, state) for a in quad.args], state)
                state = self.transfer(proc, quad, state)

    def collect(self, proc):
        self.walk(proc, self.contribute)

    def contribute(self, proc, quad, types, state):
        """What this quad tells the other procedures: argument, return, global and element types."""
        name = None if proc is self.main else proc.name.split("(")[0]
        if quad.op == "call":
            params = self.params[quad.target]
            for i, t in enumerate(types):
                params[i] |= t
        elif quad.op == "return" and name is not None:
            self.returns[name] |= types[0]
        elif quad.op == "list":
            for t in types:
                self.elements |= t
        elif quad.op == "setindex":
            self.elements |= types[2]
        elif quad.op == "append":
            self.elements |= types[1]
        if isinstance(quad.dst, Name):
            written = self.result(proc, quad, state)
            table = self.globals if name is None else self.locals[name]
            table[quad.dst.name] = table.get(quad.dst.name, NOTHING) | written

    # ------------------------------------------------------------ the checks

    def error(self, message, line):
        if not any(e.line == line and e.message == message for e in self.errors):
            self.errors.append(TypeCheckError(message, line))

    def check(self, proc, quad, types, state):
        op, line = quad.op, quad.line

        def subject(i, otherwise):
            arg = quad.args[i]
            if isinstance(arg, Name):
                return f"'{arg.name}'"
            return f"'{arg.source}'" if getattr(arg, "source", None) else otherwise

        if op == "binop" and quad.symbol not in ("==", "!="):
            for i, side in enumerate(("the left side", "the right side")):
                if types[i] == LST:
                    self.error(f"'{quad.symbol}' needs two numbers, but {subject(i, side)} is a list", line)
        elif op == "unop" and types[0] == LST:
            self.error(f"'{quad.symbol}' needs a number, but {subject(0, 'its operand')} is a list", line)
        elif op == "iffalse" and types[0] == LST:
            if quad.symbol in ("and", "or"):
                self.error(f"'{quad.symbol}' needs numbers (0 is false), but {subject(0, 'one side')} is a list", line)
            else:
                self.error(f"a condition must be a number (0 is false), but {subject(0, 'this one')} is a list", line)
        elif op in ("index", "setindex"):
            if types[0] == NUM:
                self.error(f"{subject(0, 'the value')} is a number, so it can't be indexed with [ ]", line)
            if types[1] == LST:
                self.error(f"a list index must be a number, but {subject(1, 'this one')} is a list", line)
        elif op == "len" and types[0] == NUM:
            self.error(f"len() needs a list, but {subject(0, 'its argument')} is a number", line)
        elif op == "append" and types[0] == NUM:
            self.error(f"append() needs a list first, but {subject(0, 'its first argument')} is a number", line)
