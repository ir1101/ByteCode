"""Semantic analysis: symbol tables, scope checks and warnings, before any code is generated.

Two passes over the AST:

  1. Declarations. Collect every function (so calls may come before the
     definition) and every variable each scope assigns: the global scope,
     and for each function its parameters and locals.
  2. Uses. Walk the code in order, resolving every name against those symbol
     tables and tracking which variables are *definitely assigned* at each
     point (a classic must-analysis: after an if/else, only what both branches
     assign; after a loop, only what was assigned before it).

Errors (the program is rejected):
  undefined variable or function, wrong argument count, duplicate or
  built-in function names, duplicate parameters, return / break / continue
  in the wrong place. Analysis carries on after an error, so every one is
  reported in a single run, and an unknown name gets a "did you mean" hint
  when a known name is spelled almost the same.
Warnings (the program still runs):
  a variable that may be used before it is assigned, the "scope trap" (a
  function reads a global and also assigns the same name, which creates a
  separate local), unreachable code, unused variables, parameters and
  functions, and dead stores: a value that is assigned but never read before
  it is overwritten or the program ends (found by liveness analysis, ir.py).

MiniLang's scope rule, which this mirrors: inside a function, parameters and
any assigned name are locals; other names are read from the globals.
"""

import difflib

from ast_nodes import (ArrayLit, Assign, BinOp, Block, Break, Call, Continue, ExprStmt,
                       For, FuncDef, If, Index, IndexAssign, Input, LogicalOp, Number, Print,
                       Return, UnaryOp, Var, While)
from compiler import BUILTINS
from errors import SemanticError, raise_all
from ir import build_ir

# Names from other languages, and what MiniLang does instead.
FOREIGN_NAMES = {
    "true": "MiniLang has no booleans: use 1 for true and 0 for false",
    "false": "MiniLang has no booleans: use 1 for true and 0 for false",
    "True": "MiniLang has no booleans: use 1 for true and 0 for false",
    "False": "MiniLang has no booleans: use 1 for true and 0 for false",
    "null": "MiniLang has no null value: use 0",
    "None": "MiniLang has no null value: use 0",
}
FOREIGN_FUNCTIONS = {
    "length": "a list's length is len(a)",
    "size": "a list's length is len(a)",
    "push": "add to a list with append(a, x)",
    "println": "print with the statement: print x;",
    "printf": "print with the statement: print x;",
}


def did_you_mean(name, known, foreign):
    """A hint for an unknown name: what MiniLang uses instead, or a close spelling."""
    if name in foreign:
        return f" ({foreign[name]})"
    match = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.6)
    return f" (did you mean '{match[0]}'?)" if match else ""


class Symbol:
    def __init__(self, name, kind, line):
        self.name = name
        self.kind = kind          # "global", "input", "parameter" or "local"
        self.line = line          # where it first appears
        self.assigned = []        # lines that assign it
        self.reads = []           # lines that read it

    def to_dict(self):
        return {"name": self.name, "kind": self.kind, "line": self.line,
                "assigned": sorted(set(self.assigned)), "reads": sorted(set(self.reads))}


class Function:
    def __init__(self, node):
        self.node = node
        self.name = node.name
        self.params = node.params
        self.line = node.line
        self.calls = []                   # lines that call it
        self.symbols = {}                 # parameters and locals
        self.globals_read = {}            # global name -> lines read from this function

    @property
    def signature(self):
        return f"{self.name}({', '.join(self.params)})"


class Analysis:
    """The result: symbol tables plus warnings, ready for the compiler or the UI."""

    def __init__(self):
        self.globals = {}
        self.functions = {}
        self.warnings = []

    def warn(self, line, code, message):
        if not any(w["line"] == line and w["code"] == code and w["message"] == message for w in self.warnings):
            self.warnings.append({"line": line, "code": code, "message": message})

    def to_dict(self):
        return {
            "globals": [s.to_dict() for s in sorted(self.globals.values(), key=lambda s: (s.line or 0, s.name))],
            "functions": [{
                "name": f.name, "signature": f.signature, "line": f.line, "calls": sorted(set(f.calls)),
                "symbols": [s.to_dict() for s in f.symbols.values()],
                "globals_read": [{"name": n, "reads": sorted(set(lines))} for n, lines in f.globals_read.items()],
            } for f in self.functions.values()],
            "warnings": sorted(self.warnings, key=lambda w: (w["line"] or 0, w["code"])),
        }


def analyze(program, predefined=()):
    """Check a Program. Returns an Analysis, or raises SemanticError.

    predefined: names that already exist when the program starts (a level's inputs).
    """
    return Analyzer(predefined).run(program)


class Analyzer:
    def __init__(self, predefined):
        self.result = Analysis()
        self.predefined = set(predefined)
        self.function = None   # the Function being analysed, or None at top level
        self.loop_depth = 0
        self.flagged = set()   # (scope, name): warn about an unassigned read once, at its first read
        self.errors = []
        self.unknown = set()   # (scope, name) already reported as undefined

    def error(self, message, line):
        """Record an error and keep analysing, so one run reports all of them."""
        if not any(e.line == line and e.message == message for e in self.errors):
            self.errors.append(SemanticError(message, line))

    # ------------------------------------------------------------ pass 1

    def run(self, program):
        for name in sorted(self.predefined):
            self.result.globals[name] = Symbol(name, "input", None)
        for stmt in program.statements:
            if isinstance(stmt, FuncDef):
                self.declare_function(stmt)
            else:
                for name, line in assignments_in(stmt):
                    self.global_symbol(name, line).assigned.append(line)
        for fn in self.result.functions.values():
            for param in fn.params:
                fn.symbols[param] = Symbol(param, "parameter", fn.line)
                fn.symbols[param].assigned.append(fn.line)  # given a value on every call
            for name, line in assignments_in(fn.node.body):
                if name not in fn.symbols:
                    fn.symbols[name] = Symbol(name, "local", line)
                fn.symbols[name].assigned.append(line)

        # ---------------------------------------------------------- pass 2
        assigned = set(self.predefined)
        for stmt in program.statements:
            if isinstance(stmt, FuncDef):
                fn = self.result.functions.get(stmt.name)
                if fn is not None and fn.node is stmt:   # not a rejected duplicate
                    self.check_function(fn)
            elif assigned is None:
                self.result.warn(stmt.line, "unreachable", "this code can never run")
            else:
                assigned = self.stmt(stmt, assigned)
        if self.errors:
            raise_all(self.errors)
        self.report_unused()
        self.report_dead_stores(program)
        return self.result

    def global_symbol(self, name, line):
        if name not in self.result.globals:
            self.result.globals[name] = Symbol(name, "global", line)
        return self.result.globals[name]

    def declare_function(self, node):
        if node.name in BUILTINS:
            return self.error(f"'{node.name}' is a built-in function and can't be redefined", node.line)
        if node.name in self.result.functions:
            first = self.result.functions[node.name].line
            return self.error(f"function '{node.name}' is already defined on line {first}", node.line)
        seen = set()
        for param in node.params:
            if param in seen:
                self.error(f"duplicate parameter '{param}' in function '{node.name}'", node.line)
            seen.add(param)
        self.result.functions[node.name] = Function(node)

    # ------------------------------------------------------------ pass 2

    def check_function(self, fn):
        outer = (self.function, self.loop_depth)
        self.function, self.loop_depth = fn, 0
        self.block(fn.node.body.statements, set(fn.params))
        self.function, self.loop_depth = outer

    def block(self, statements, assigned):
        """Analyse statements in order. Returns the definitely-assigned set, or None if
        control can't reach the end (after return, break or continue)."""
        for stmt in statements:
            if assigned is None:
                self.result.warn(stmt.line, "unreachable", "this code can never run")
                return None
            assigned = self.stmt(stmt, assigned)
        return assigned

    def stmt(self, node, assigned):
        if isinstance(node, Assign):
            self.expr(node.value, assigned)
            return assigned | {node.name}
        if isinstance(node, Input):
            return assigned | {node.name}
        if isinstance(node, IndexAssign):
            for part in (node.target, node.index, node.value):
                self.expr(part, assigned)
            return assigned
        if isinstance(node, (Print, ExprStmt)):
            self.expr(node.value if isinstance(node, Print) else node.expr, assigned)
            return assigned
        if isinstance(node, Block):
            return self.block(node.statements, assigned)
        if isinstance(node, If):
            self.expr(node.condition, assigned)
            then_out = self.block(node.then_body.statements, assigned)
            else_out = assigned if node.else_body is None else self.stmt(node.else_body, assigned)
            return meet(then_out, else_out)
        if isinstance(node, While):
            self.expr(node.condition, assigned)
            self.loop_body(node.body, assigned)
            return assigned        # the body may run zero times
        if isinstance(node, For):
            if node.init is not None:
                assigned = self.stmt(node.init, assigned)
            if node.condition is not None:
                self.expr(node.condition, assigned)
            self.loop_body(node.body, assigned)
            if node.update is not None:
                self.stmt(node.update, assigned)
            return assigned
        if isinstance(node, Return):
            if node.value is not None:
                self.expr(node.value, assigned)
            if self.function is None:
                self.error("'return' outside a function", node.line)
                return assigned   # keep checking the code after it
            return None
        if isinstance(node, (Break, Continue)):
            if self.loop_depth == 0:
                word = "break" if isinstance(node, Break) else "continue"
                self.error(f"'{word}' outside a loop", node.line)
                return assigned
            return None
        if isinstance(node, FuncDef):
            self.error("functions can only be defined at the top level", node.line)
            return assigned
        raise SemanticError(f"unexpected statement {type(node).__name__}", node.line)

    def loop_body(self, body, assigned):
        self.loop_depth += 1
        self.block(body.statements, assigned)
        self.loop_depth -= 1

    def expr(self, node, assigned):
        if isinstance(node, Var):
            self.read(node, assigned)
        elif isinstance(node, Number):
            pass
        elif isinstance(node, (BinOp, LogicalOp)):
            self.expr(node.left, assigned)
            self.expr(node.right, assigned)
        elif isinstance(node, UnaryOp):
            self.expr(node.operand, assigned)
        elif isinstance(node, ArrayLit):
            for item in node.items:
                self.expr(item, assigned)
        elif isinstance(node, Index):
            self.expr(node.target, assigned)
            self.expr(node.index, assigned)
        elif isinstance(node, Call):
            self.call(node, assigned)
        else:
            raise SemanticError(f"unexpected expression {type(node).__name__}", node.line)

    def call(self, node, assigned):
        for arg in node.args:
            self.expr(arg, assigned)
        if node.name in BUILTINS:
            arity = BUILTINS[node.name][1]
            if len(node.args) != arity:
                self.error(f"built-in '{node.name}' takes {arity} argument(s), "
                           f"but {len(node.args)} were given", node.line)
            return
        fn = self.result.functions.get(node.name)
        if fn is None:
            known = set(self.result.functions) | set(BUILTINS)
            hint = did_you_mean(node.name, known, FOREIGN_FUNCTIONS)
            return self.error(f"undefined function '{node.name}'{hint}", node.line)
        if len(node.args) != len(fn.params):
            self.error(f"function '{node.name}' takes {len(fn.params)} argument(s), "
                       f"but {len(node.args)} were given", node.line)
        fn.calls.append(node.line)

    def read(self, node, assigned):
        name, line = node.name, node.line
        fn = self.function
        scope = fn.name if fn is not None else None
        if name not in assigned:
            if (scope, name) in self.flagged:
                assigned = assigned | {name}  # already reported for this scope
            else:
                self.flagged.add((scope, name))
        if fn is not None and name in fn.symbols:
            fn.symbols[name].reads.append(line)
            if name not in assigned:
                if name in self.result.globals:
                    # The local may have no value yet, so this read can reach the global.
                    self.result.globals[name].reads.append(line)
                    fn.globals_read.setdefault(name, []).append(line)
                    first = min(fn.symbols[name].assigned)
                    self.result.warn(line, "scope-trap",
                        f"'{name}' is read here before {fn.name}() assigns it, so this reads the global "
                        f"'{name}'. The assignment on line {first} creates a separate local '{name}': "
                        f"the global never changes.")
                else:
                    self.result.warn(line, "maybe-unassigned", f"'{name}' may be used before it is assigned")
            return
        if name in self.result.globals:
            self.result.globals[name].reads.append(line)
            if fn is not None:
                fn.globals_read.setdefault(name, []).append(line)
            elif name not in assigned:
                self.result.warn(line, "maybe-unassigned", f"'{name}' may be used before it is assigned")
            return
        if (scope, name) in self.unknown:
            return   # already reported at its first use in this scope
        self.unknown.add((scope, name))
        known = set(self.result.globals) | (set(fn.symbols) if fn is not None else set())
        where = f" in {fn.name}()" if fn is not None else ""
        self.error(f"undefined variable '{name}'{where}{did_you_mean(name, known, FOREIGN_NAMES)}", line)

    def report_unused(self):
        for sym in self.result.globals.values():
            if sym.kind == "global" and not sym.reads:
                self.result.warn(sym.line, "unused", f"'{sym.name}' is assigned but never used")
        for fn in self.result.functions.values():
            if not fn.calls:
                self.result.warn(fn.line, "unused", f"function '{fn.name}' is never called")
            for sym in fn.symbols.values():
                if sym.reads:
                    continue
                if sym.kind == "parameter":
                    self.result.warn(fn.line, "unused", f"parameter '{sym.name}' of {fn.name}() is never used")
                else:
                    self.result.warn(sym.line, "unused",
                                     f"'{sym.name}' is assigned in {fn.name}() but never used there")


    def report_dead_stores(self, program):
        """Stores whose value no path reads. A variable that is never read at all
        already has an 'unused' warning, and a line keeps the warning it already has."""
        warned = {w["line"] for w in self.result.warnings}
        for proc, node in build_ir(program).dead_stores:
            if proc.name == "main":
                sym = self.result.globals.get(node.name)
            else:
                fn = self.result.functions.get(proc.name.split("(")[0])
                sym = fn.symbols.get(node.name) if fn is not None else None
            if sym is None or not sym.reads or node.line in warned:
                continue
            self.result.warn(node.line, "dead-store",
                             f"the value assigned to '{node.name}' here is never read: it is "
                             "assigned again, or the program ends, before anything uses it")


def meet(a, b):
    """Definitely assigned after two paths join. None means 'this path never gets here'."""
    if a is None:
        return b
    if b is None:
        return a
    return a & b


def assignments_in(node):
    """(name, line) for every plain assignment (or input) inside node, not looking into functions."""
    if isinstance(node, (Assign, Input)):
        yield node.name, node.line
    elif isinstance(node, Block):
        for stmt in node.statements:
            yield from assignments_in(stmt)
    elif isinstance(node, If):
        yield from assignments_in(node.then_body)
        if node.else_body is not None:
            yield from assignments_in(node.else_body)
    elif isinstance(node, While):
        yield from assignments_in(node.body)
    elif isinstance(node, For):
        for part in (node.init, node.update, node.body):
            if part is not None:
                yield from assignments_in(part)


def format_symbols(analysis):
    """A plain-text symbol table, for main.py --debug."""
    lines = ["global scope:"]
    for sym in sorted(analysis.globals.values(), key=lambda s: (s.line or 0, s.name)):
        lines.append(f"  {sym.name:<14}{sym.kind:<11}assigned {_lines(sym.assigned):<14}read {_lines(sym.reads)}")
    for fn in analysis.functions.values():
        lines.append(f"function {fn.signature}  (line {fn.line}, called on {_lines(fn.calls)})")
        for sym in fn.symbols.values():
            lines.append(f"  {sym.name:<14}{sym.kind:<11}assigned {_lines(sym.assigned):<14}read {_lines(sym.reads)}")
        for name, reads in fn.globals_read.items():
            lines.append(f"  {name:<14}{'global':<11}{'':<23}read {_lines(reads)}")
    return "\n".join(lines)


def _lines(numbers):
    unique = sorted(set(n for n in numbers if n is not None))
    return ", ".join(map(str, unique)) if unique else "-"
