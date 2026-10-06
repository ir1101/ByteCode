"""Intermediate representation: three-address code, basic blocks, a control-flow
graph, and three data-flow analyses over it.

1. Lowering. The AST becomes three-address code (TAC): simple instructions with
   at most one operator, e.g.  t1 = n * 2 ;  x = t1 + 1 ;  if_false t2 goto L3.
   Each function, and the top-level code ("main"), is a separate procedure.

2. Basic blocks. A *leader* starts a new block: the first instruction, every
   label, and every instruction right after a jump or return. Edges join a block
   to the blocks it can jump or fall through to, giving the control-flow graph.

3. Constant propagation (Kildall's iterative data-flow algorithm). For each
   block we compute which variables hold a known constant on entry: the meet of
   its predecessors' exit states (a variable stays constant only if every
   incoming path agrees on its value). Blocks are revisited until nothing
   changes. A branch whose condition is a known constant only follows its taken
   edge, so dead branches don't spoil the facts that reach the join point.

4. Liveness (a backward "may" analysis). A variable is live at a point if its
   current value may still be read on some path from there. live_out(B) is the
   union of live_in over B's successors, and live_in(B) = use(B) + (live_out(B)
   - def(B)). A store to a variable that is not live just after it is a *dead
   store*: its value is overwritten or the program ends before anyone reads it.

5. Definite assignment (a forward "must" analysis, meet = intersection): which
   variables surely hold a value at each point. Reading one of those can never
   fail with "undefined variable", which tells the optimizer that deleting such
   a read (inside a dead store) cannot hide a runtime error.

The optimizer uses the results: every variable read that is provably constant is
replaced by that constant in the AST before constant folding, and dead stores
whose right-hand side can't fail or have side effects are deleted (see
optimizer.optimize). Semantic analysis turns dead stores into warnings.
"""

from types import SimpleNamespace

from ast_nodes import (ArrayLit, Assign, BinOp, Block as BlockNode, Break, Call, Continue,
                       ExprStmt, For, FuncDef, If, Index, IndexAssign, LogicalOp, Number,
                       Print, Return, UnaryOp, Var, While)
from compiler import BINARY_OPCODES, BUILTINS
from vm import apply_binary

# --------------------------------------------------------------------------- #
#  Operands and instructions
# --------------------------------------------------------------------------- #


class Const:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return str(self.value)


class Name:
    """A program variable. `node` is the AST Var it was read from (None when written)."""

    def __init__(self, name, node=None):
        self.name = name
        self.node = node

    def __str__(self):
        return self.name


class Temp:
    """A compiler temporary, shown as t1, t2, ... Its data-flow key is "%t1": '%' can't
    appear in a MiniLang name, so a temp never collides with a user variable called t1."""

    def __init__(self, number):
        self.name = f"%t{number}"

    def __str__(self):
        return self.name[1:]


def _var_key(operand):
    """The data-flow key for an operand that can hold a value, else None."""
    return operand.name if isinstance(operand, (Name, Temp)) else None


class Quad:
    """One three-address instruction."""

    def __init__(self, op, dst=None, args=(), target=None, symbol=None, line=None):
        self.op = op            # copy binop unop list index setindex len append call print return goto iffalse label
        self.dst = dst          # Name or Temp written, if any
        self.args = list(args)  # operands read
        self.target = target    # label (goto / iffalse / label) or function name (call)
        self.symbol = symbol    # '+', '-', 'not', ...
        self.line = line
        self.origin = None      # the AST Assign whose value this quad stores, if any

    def __str__(self):
        a = [str(x) for x in self.args]
        lhs = f"{self.dst} = " if self.dst is not None else ""
        if self.op == "copy":
            return f"{lhs}{a[0]}"
        if self.op == "binop":
            return f"{lhs}{a[0]} {self.symbol} {a[1]}"
        if self.op == "unop":
            return f"{lhs}{self.symbol} {a[0]}" if self.symbol == "not" else f"{lhs}-{a[0]}"
        if self.op == "list":
            return f"{lhs}[{', '.join(a)}]"
        if self.op == "index":
            return f"{lhs}{a[0]}[{a[1]}]"
        if self.op == "setindex":
            return f"{a[0]}[{a[1]}] = {a[2]}"
        if self.op in ("len", "append"):
            return f"{lhs}{self.op}({', '.join(a)})"
        if self.op == "call":
            return f"{lhs}call {self.target}({', '.join(a)})"
        if self.op == "print":
            return f"print {a[0]}"
        if self.op == "return":
            return f"return {a[0]}"
        if self.op == "goto":
            return f"goto {self.target}"
        if self.op == "iffalse":
            return f"if_false {a[0]} goto {self.target}"
        if self.op == "label":
            return f"{self.target}:"
        raise ValueError(self.op)


# --------------------------------------------------------------------------- #
#  1. Lowering the AST to three-address code
# --------------------------------------------------------------------------- #


class Procedure:
    def __init__(self, name, params=()):
        self.name = name        # "main" or a signature such as "fact(n)"
        self.params = list(params)
        self.quads = []
        self.blocks = []        # filled by build_cfg()


class Lowerer:
    def __init__(self):
        self.temps = 0
        self.labels = 0
        self.code = None
        self.loops = []         # (continue label, break label), innermost last

    def new_temp(self):
        self.temps += 1
        return Temp(self.temps)

    def new_label(self):
        self.labels += 1
        return f"L{self.labels}"

    def emit(self, *args, **kwargs):
        self.code.append(Quad(*args, **kwargs))

    def lower(self, program):
        main = Procedure("main")
        self.code = main.quads
        for stmt in program.statements:
            if not isinstance(stmt, FuncDef):
                self.stmt(stmt)
        procedures = [main]
        for stmt in program.statements:
            if isinstance(stmt, FuncDef):
                proc = Procedure(f"{stmt.name}({', '.join(stmt.params)})", stmt.params)
                self.code, self.loops = proc.quads, []
                for s in stmt.body.statements:
                    self.stmt(s)
                self.emit("return", args=[Const(0)], line=stmt.line)   # falling off the end returns 0
                procedures.append(proc)
        return procedures

    # ----- statements -----
    def stmt(self, node):
        if isinstance(node, Assign):
            self.expr(node.value, dst=Name(node.name))
            self.code[-1].origin = node   # the quad that finally stores the value
        elif isinstance(node, IndexAssign):
            target, index = self.expr(node.target), self.expr(node.index)
            self.emit("setindex", args=[target, index, self.expr(node.value)], line=node.line)
        elif isinstance(node, Print):
            self.emit("print", args=[self.expr(node.value)], line=node.line)
        elif isinstance(node, ExprStmt):
            self.expr(node.expr)
        elif isinstance(node, BlockNode):
            for s in node.statements:
                self.stmt(s)
        elif isinstance(node, If):
            cond = self.expr(node.condition)
            end = self.new_label()
            if node.else_body is None:
                self.emit("iffalse", args=[cond], target=end, line=node.line)
                self.stmt(node.then_body)
            else:
                otherwise = self.new_label()
                self.emit("iffalse", args=[cond], target=otherwise, line=node.line)
                self.stmt(node.then_body)
                self.emit("goto", target=end, line=node.line)
                self.emit("label", target=otherwise)
                self.stmt(node.else_body)
            self.emit("label", target=end)
        elif isinstance(node, While):
            start, end = self.new_label(), self.new_label()
            self.emit("label", target=start)
            self.emit("iffalse", args=[self.expr(node.condition)], target=end, line=node.line)
            self.loop(node.body, start, end)
            self.emit("goto", target=start, line=node.line)
            self.emit("label", target=end)
        elif isinstance(node, For):
            if node.init is not None:
                self.stmt(node.init)
            start, step, end = self.new_label(), self.new_label(), self.new_label()
            self.emit("label", target=start)
            if node.condition is not None:
                self.emit("iffalse", args=[self.expr(node.condition)], target=end, line=node.line)
            self.loop(node.body, step, end)
            self.emit("label", target=step)
            if node.update is not None:
                self.stmt(node.update)
            self.emit("goto", target=start, line=node.line)
            self.emit("label", target=end)
        elif isinstance(node, Break):
            self.emit("goto", target=self.loops[-1][1], line=node.line)
        elif isinstance(node, Continue):
            self.emit("goto", target=self.loops[-1][0], line=node.line)
        elif isinstance(node, Return):
            value = Const(0) if node.value is None else self.expr(node.value)
            self.emit("return", args=[value], line=node.line)
        else:
            raise ValueError(f"cannot lower {type(node).__name__}")

    def loop(self, body, continue_label, break_label):
        self.loops.append((continue_label, break_label))
        self.stmt(body)
        self.loops.pop()

    # ----- expressions: return the operand holding the value -----
    def expr(self, node, dst=None):
        if isinstance(node, Number):
            return self.place(Const(node.value), dst, node.line)
        if isinstance(node, Var):
            return self.place(Name(node.name, node), dst, node.line)
        if isinstance(node, BinOp):
            left, right = self.expr(node.left), self.expr(node.right)
            out = dst or self.new_temp()
            self.emit("binop", dst=out, args=[left, right], symbol=node.op, line=node.line)
            return out
        if isinstance(node, UnaryOp):
            operand = self.expr(node.operand)
            out = dst or self.new_temp()
            self.emit("unop", dst=out, args=[operand], symbol=node.op, line=node.line)
            return out
        if isinstance(node, LogicalOp):
            return self.place(self.logical(node), dst, node.line)
        if isinstance(node, ArrayLit):
            items = [self.expr(item) for item in node.items]
            out = dst or self.new_temp()
            self.emit("list", dst=out, args=items, line=node.line)
            return out
        if isinstance(node, Index):
            target, index = self.expr(node.target), self.expr(node.index)
            out = dst or self.new_temp()
            self.emit("index", dst=out, args=[target, index], line=node.line)
            return out
        if isinstance(node, Call):
            args = [self.expr(a) for a in node.args]
            out = dst or self.new_temp()
            if node.name in BUILTINS:
                self.emit(node.name, dst=out, args=args, line=node.line)
            else:
                self.emit("call", dst=out, args=args, target=node.name, line=node.line)
            return out
        raise ValueError(f"cannot lower {type(node).__name__}")

    def place(self, operand, dst, line):
        """Copy operand into dst when the caller asked for a specific destination."""
        if dst is None:
            return operand
        self.emit("copy", dst=dst, args=[operand], line=line)
        return dst

    def logical(self, node):
        """Short-circuit and/or with jumps; the result (0 or 1) lands in a temp."""
        out = self.new_temp()
        false_label, end = self.new_label(), self.new_label()
        left = self.expr(node.left)
        if node.op == "and":
            self.emit("iffalse", args=[left], target=false_label, line=node.line)
        else:
            try_right = self.new_label()
            self.emit("iffalse", args=[left], target=try_right, line=node.line)
            self.emit("copy", dst=out, args=[Const(1)], line=node.line)
            self.emit("goto", target=end, line=node.line)
            self.emit("label", target=try_right)
        right = self.expr(node.right)
        self.emit("iffalse", args=[right], target=false_label, line=node.line)
        self.emit("copy", dst=out, args=[Const(1)], line=node.line)
        self.emit("goto", target=end, line=node.line)
        self.emit("label", target=false_label)
        self.emit("copy", dst=out, args=[Const(0)], line=node.line)
        self.emit("label", target=end)
        return out


# --------------------------------------------------------------------------- #
#  2. Basic blocks and the control-flow graph
# --------------------------------------------------------------------------- #

JUMPS = {"goto", "iffalse"}


class BasicBlock:
    def __init__(self, number):
        self.id = f"B{number}"
        self.labels = []        # labels that name this block's first instruction
        self.quads = []
        self.succ = []          # block ids
        self.pred = []

    @property
    def label(self):
        return "/".join(self.labels) or None


def build_cfg(proc):
    """Split a procedure's quads into basic blocks and connect them."""
    blocks, current = [], None

    def new_block():
        block = BasicBlock(len(blocks))
        blocks.append(block)
        return block

    for quad in proc.quads:
        if quad.op == "label":
            # A label is a leader: it starts a new block (two labels in a row share one).
            if current is None or current.quads:
                current = new_block()
            current.labels.append(quad.target)
            continue
        # The instruction after a jump or return is a leader too.
        if current is None or (current.quads and current.quads[-1].op in JUMPS | {"return"}):
            current = new_block()
        current.quads.append(quad)
    if not blocks:
        new_block()

    by_label = {name: block.id for block in blocks for name in block.labels}
    for i, block in enumerate(blocks):
        last = block.quads[-1] if block.quads else None
        falls_through = i + 1 < len(blocks)
        if last is not None and last.op == "goto":
            block.succ = [by_label[last.target]]
        elif last is not None and last.op == "iffalse":
            block.succ = ([blocks[i + 1].id] if falls_through else []) + [by_label[last.target]]
        elif last is not None and last.op == "return":
            block.succ = []
        elif falls_through:
            block.succ = [blocks[i + 1].id]
    by_id = {b.id: b for b in blocks}
    for block in blocks:
        for s in block.succ:
            if block.id not in by_id[s].pred:
                by_id[s].pred.append(block.id)
    proc.blocks = blocks
    return blocks


# --------------------------------------------------------------------------- #
#  3. Constant propagation
# --------------------------------------------------------------------------- #
# A state maps a variable to its known constant. A missing name means "not a
# constant" (or "may be undefined"); None means "this point is unreachable".


def meet(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return {k: v for k, v in a.items() if k in b and b[k] == v}


def value_of(operand, state):
    if isinstance(operand, Const):
        return operand.value
    key = _var_key(operand)
    return state.get(key) if key is not None else None


def evaluate(quad, state):
    """The constant a quad writes, or None if it isn't a compile-time constant."""
    vals = [value_of(a, state) for a in quad.args]
    if any(isinstance(v, list) for v in vals):
        return None
    if quad.op == "copy":
        return vals[0]
    if quad.op == "binop" and None not in vals:
        opcode = BINARY_OPCODES[quad.symbol]
        if opcode in ("DIV", "MOD") and vals[1] == 0:
            return None  # leave the runtime error in place
        return apply_binary(opcode, vals[0], vals[1])
    if quad.op == "unop" and vals[0] is not None:
        return -vals[0] if quad.symbol == "-" else int(vals[0] == 0)
    return None  # lists, indexing, calls, len, append: not constants


def transfer(quad, state):
    if quad.dst is not None:
        value = evaluate(quad, state)
        state = dict(state)
        if value is None:
            state.pop(quad.dst.name, None)
        else:
            state[quad.dst.name] = value
    return state


def live_successors(block, state):
    """Successors that can actually be taken, given the exit state."""
    last = block.quads[-1] if block.quads else None
    if last is not None and last.op == "iffalse" and len(block.succ) == 2:
        cond = value_of(last.args[0], state)
        if cond is not None:
            return [block.succ[1]] if cond == 0 else [block.succ[0]]
    return block.succ


def propagate(proc):
    """Kildall's algorithm. Returns {block id: entry state} (None = unreachable)."""
    blocks = proc.blocks
    by_id = {b.id: b for b in blocks}
    entry = {b.id: None for b in blocks}
    out = {b.id: None for b in blocks}
    entry[blocks[0].id] = {}            # nothing is known when a procedure starts
    changed = True
    while changed:
        changed = False
        for block in blocks:
            if block is blocks[0]:
                incoming = {}  # the procedure's entry: meet with "nothing known" is nothing known
            else:
                incoming = None
                for p in block.pred:
                    if out[p] is not None and block.id in live_successors(by_id[p], out[p]):
                        incoming = meet(incoming, out[p])
            if incoming is None:
                continue  # no executable path reaches this block (yet)
            state = incoming
            for quad in block.quads:
                state = transfer(quad, state)
            if incoming != entry[block.id] or state != out[block.id]:
                entry[block.id], out[block.id] = incoming, state
                changed = True
    return entry


# --------------------------------------------------------------------------- #
#  4. Liveness and dead stores
# --------------------------------------------------------------------------- #


def uses_of(quad, call_uses):
    """Variables a quad reads. A call may also read any global a function reads."""
    used = {key for key in map(_var_key, quad.args) if key is not None}
    if quad.op == "call":
        used |= call_uses
    return used


def live_after_each(quads, live_out, call_uses):
    """Walk a block backwards from live_out. Returns (live set just after each quad, live_in)."""
    after = [None] * len(quads)
    live = set(live_out)
    for i in range(len(quads) - 1, -1, -1):
        after[i] = frozenset(live)
        quad = quads[i]
        if quad.dst is not None:
            live.discard(quad.dst.name)   # kill the definition first: x = x + 1 still reads x
        live |= uses_of(quad, call_uses)
    return after, live


def liveness(blocks, call_uses=frozenset()):
    """Iterate to a fixed point. Returns ({block id: live_in}, {block id: live_out})."""
    live_in = {b.id: set() for b in blocks}
    live_out = {b.id: set() for b in blocks}
    changed = True
    while changed:
        changed = False
        for block in reversed(blocks):   # a backward problem converges faster in reverse order
            out = set().union(*(live_in[s] for s in block.succ))
            _, inn = live_after_each(block.quads, out, call_uses)
            if out != live_out[block.id] or inn != live_in[block.id]:
                live_out[block.id], live_in[block.id] = out, inn
                changed = True
    return live_in, live_out


def globals_read_by_functions(procedures, safe_reads):
    """Names a function may read from the globals: every read that isn't of a parameter
    or a local surely assigned by then. A call in main may read any of these."""
    return frozenset(arg.name for proc in procedures[1:] for quad in proc.quads for arg in quad.args
                     if isinstance(arg, Name) and id(arg.node) not in safe_reads)


# --------------------------------------------------------------------------- #
#  5. Definite assignment
# --------------------------------------------------------------------------- #


def definitely_assigned(proc):
    """{block id: names surely assigned on entry}, or None for an unreachable block."""
    blocks = proc.blocks
    entry = {b.id: None for b in blocks}
    out = {b.id: None for b in blocks}
    changed = True
    while changed:
        changed = False
        for block in blocks:
            if block is blocks[0]:
                incoming = set(proc.params)   # a procedure starts with only its parameters
            else:
                incoming = None
                for p in block.pred:
                    if out[p] is not None:
                        incoming = set(out[p]) if incoming is None else incoming & out[p]
            if incoming is None:
                continue
            state = incoming | {q.dst.name for q in block.quads if q.dst is not None}
            if incoming != entry[block.id] or state != out[block.id]:
                entry[block.id], out[block.id] = incoming, state
                changed = True
    return entry


def harmless(node, safe_reads):
    """True if evaluating this expression can't fail and has no side effects,
    so deleting it can't change what the program prints or which error it raises."""
    if isinstance(node, Number):
        return True
    if isinstance(node, Var):
        return id(node) in safe_reads              # surely assigned: can't be "undefined"
    if isinstance(node, ArrayLit):
        return all(harmless(item, safe_reads) for item in node.items)
    if isinstance(node, BinOp) and node.op in ("==", "!="):   # the only operators that accept lists
        return harmless(node.left, safe_reads) and harmless(node.right, safe_reads)
    return False   # arithmetic (lists, division by zero), indexing, calls, not/and/or


def harmless_quad(quad, safe_reads):
    """The same test for a quad of the optimized three-address code."""
    def ok(arg):
        return isinstance(arg, (Const, Temp)) or (isinstance(arg, Name) and id(arg.node) in safe_reads)
    if quad.op in ("copy", "list"):
        return all(ok(a) for a in quad.args)
    return quad.op == "binop" and quad.symbol in ("==", "!=") and all(ok(a) for a in quad.args)


# --------------------------------------------------------------------------- #
#  Putting it together
# --------------------------------------------------------------------------- #


class IR:
    def __init__(self, program):
        self.procedures = Lowerer().lower(program)
        self.facts = {}           # proc name -> {block id: entry state}
        self.constants = {}       # id(AST Var node) -> constant value read there
        self.live = {}            # proc name -> ({block id: live_in}, {block id: live_out})
        self.dead = {}            # proc name -> {block id: indexes of dead stores}
        self.dead_stores = []     # (procedure, Assign node) whose stored value is never read
        self.safe_reads = set()   # id(AST Var node) of reads that can't be undefined
        self.removable = set()    # id(AST Assign node) the optimizer may delete
        self._optimized = {}      # proc name -> (rewritten quads per block, dead-store indexes)
        for proc in self.procedures:
            build_cfg(proc)
            self._find_safe_reads(proc)
        self.call_uses = globals_read_by_functions(self.procedures, self.safe_reads)
        for proc in self.procedures:
            entry = propagate(proc)
            self.facts[proc.name] = entry
            for block in proc.blocks:
                state = entry[block.id]
                if state is None:
                    continue
                for quad in block.quads:
                    for arg in quad.args:
                        if isinstance(arg, Name) and arg.node is not None and arg.name in state:
                            self.constants[id(arg.node)] = state[arg.name]
                    state = transfer(quad, state)
            self._find_dead_stores(proc)

    def uses_for(self, proc):
        return self.call_uses if proc.name == "main" else frozenset()

    def _find_safe_reads(self, proc):
        entry = definitely_assigned(proc)
        for block in proc.blocks:
            assigned = entry[block.id]
            if assigned is None:
                continue
            assigned = set(assigned)
            for quad in block.quads:
                for arg in quad.args:
                    if isinstance(arg, Name) and arg.node is not None and arg.name in assigned:
                        self.safe_reads.add(id(arg.node))
                if quad.dst is not None:
                    assigned.add(quad.dst.name)

    def _find_dead_stores(self, proc):
        live_in, live_out = liveness(proc.blocks, self.uses_for(proc))
        self.live[proc.name] = (live_in, live_out)
        reachable = self.facts[proc.name]
        dead = self.dead[proc.name] = {}
        for block in proc.blocks:
            after, _ = live_after_each(block.quads, live_out[block.id], self.uses_for(proc))
            dead[block.id] = []
            for i, quad in enumerate(block.quads):
                if quad.origin is not None and quad.dst.name not in after[i]:
                    dead[block.id].append(i)
                    if reachable[block.id] is not None:   # unreachable code has its own warning
                        self.dead_stores.append((proc, quad.origin))
                        if harmless(quad.origin.value, self.safe_reads):
                            self.removable.add(id(quad.origin))

    # ----- the optimized view: constants substituted, then dead stores removed -----
    def optimized(self, proc):
        """({block id: rewritten quads}, {block id: indexes removed as dead stores})."""
        if proc.name not in self._optimized:
            facts = self.facts[proc.name]
            quads, blocks = {}, []
            for block in proc.blocks:
                state = facts[block.id]
                if state is None:
                    continue   # unreachable: removed entirely
                rewritten = []
                for quad in block.quads:
                    new = self.rewrite(quad, state)
                    if new is not None:
                        rewritten.append(new)
                    state = transfer(quad, state)
                quads[block.id] = rewritten
                blocks.append(SimpleNamespace(id=block.id, quads=rewritten,
                                              succ=[s for s in live_successors(block, state)]))
            removed = {b.id: set() for b in blocks}
            changed = True
            while changed:   # deleting one dead store can make another one dead
                changed = False
                for b in blocks:
                    b.quads = [q for i, q in enumerate(quads[b.id]) if i not in removed[b.id]]
                _, live_out = liveness(blocks, self.uses_for(proc))
                for b in blocks:
                    kept = [i for i in range(len(quads[b.id])) if i not in removed[b.id]]
                    after, _ = live_after_each([quads[b.id][i] for i in kept], live_out[b.id], self.uses_for(proc))
                    for j, i in enumerate(kept):
                        q = quads[b.id][i]
                        if q.dst is not None and q.dst.name not in after[j] and harmless_quad(q, self.safe_reads):
                            removed[b.id].add(i)
                            changed = True
            self._optimized[proc.name] = (quads, {k: sorted(v) for k, v in removed.items()})
        return self._optimized[proc.name]

    def rewrite(self, quad, state):
        """The quad with known constants substituted and folded; None if it disappears."""
        if quad.dst is not None and quad.op in ("copy", "binop", "unop"):
            value = evaluate(quad, state)
            if value is not None:
                return Quad("copy", quad.dst, [Const(value)], line=quad.line)
        if quad.op == "iffalse":
            cond = value_of(quad.args[0], state)
            if cond is not None:   # a decided branch: always taken, or never (then drop it)
                return Quad("goto", target=quad.target, line=quad.line) if cond == 0 else None
        args = []
        for arg in quad.args:
            value = value_of(arg, state)
            args.append(Const(value) if value is not None and not isinstance(value, list) else arg)
        return Quad(quad.op, quad.dst, args, quad.target, quad.symbol, quad.line)

    def optimized_lines(self, proc, block):
        """The block's TAC after substituting and folding constants (dead stores included)."""
        return [str(q) for q in self.optimized(proc)[0].get(block.id, [])]

    # ----- rendering -----
    def stats(self):
        quads = sum(len(b.quads) for p in self.procedures for b in p.blocks)
        blocks = sum(len(p.blocks) for p in self.procedures)
        unreachable = sum(1 for p in self.procedures for b in p.blocks if self.facts[p.name][b.id] is None)
        removed = sum(len(v) for p in self.procedures for v in self.optimized(p)[1].values())
        return {"procedures": len(self.procedures), "blocks": blocks, "instructions": quads,
                "constant_reads": len(self.constants), "unreachable_blocks": unreachable,
                "dead_stores": len(self.dead_stores), "removed_stores": removed}

    def to_dict(self):
        procs = []
        for proc in self.procedures:
            facts = self.facts[proc.name]
            live_in, live_out = self.live[proc.name]
            _, removed = self.optimized(proc)
            procs.append({
                "name": proc.name,
                "blocks": [{
                    "id": b.id,
                    "label": b.label,
                    "lines": [str(q) for q in b.quads],
                    "source_lines": [q.line for q in b.quads],
                    "optimized": self.optimized_lines(proc, b),
                    "optimized_dead": removed.get(b.id, []),
                    "dead": self.dead[proc.name][b.id],
                    "succ": b.succ,
                    "pred": b.pred,
                    "reachable": facts[b.id] is not None,
                    "constants_in": {k: v for k, v in sorted((facts[b.id] or {}).items()) if not _is_temp(k)},
                    "live_in": sorted(n for n in live_in[b.id] if not _is_temp(n)),
                    "live_out": sorted(n for n in live_out[b.id] if not _is_temp(n)),
                } for b in proc.blocks],
            })
        return {"procedures": procs, "stats": self.stats()}

    def format(self):
        """Plain text for main.py --debug."""
        out = []
        for proc in self.procedures:
            out.append(f"procedure {proc.name}")
            live_in, live_out = self.live[proc.name]
            for b in proc.blocks:
                facts = self.facts[proc.name][b.id]
                head = f"  {b.id}" + (f" ({b.label})" if b.label else "")
                head += f"  -> {', '.join(b.succ) if b.succ else 'exit'}"
                if facts is None:
                    head += "  [unreachable]"
                elif any(not _is_temp(k) for k in facts):
                    head += "  constants in: " + ", ".join(f"{k}={v}" for k, v in sorted(facts.items())
                                                           if not _is_temp(k))
                out.append(head)
                out.append(f"      live in: {_names(live_in[b.id])}   live out: {_names(live_out[b.id])}")
                dead = self.dead[proc.name][b.id]
                for i, q in enumerate(b.quads):
                    out.append(f"      {q}" + ("    <- dead store" if i in dead else ""))
        return "\n".join(out)


def _is_temp(name):
    return name.startswith("%")


def _names(names):
    shown = sorted(n for n in names if not _is_temp(n))
    return ", ".join(shown) if shown else "-"


def build_ir(program):
    return IR(program)


def constant_reads(program):
    """{id(Var node): value} for every variable read that is provably constant."""
    return IR(program).constants


def removable_stores(program):
    """{id(Assign node)} for dead stores the optimizer can delete without changing behaviour."""
    return IR(program).removable
