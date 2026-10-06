"""Optimizer: four passes that never change what a program prints or which error it raises.

  1. Constant propagation (ir.py): data-flow analysis over the control-flow
     graph finds every variable read whose value is the same constant on
     every path. Those reads become literals.
  2. Constant folding on the AST: 2 * 3 + 4 becomes 10, `0 and f()` becomes 0.
  3. Dead-store elimination (liveness analysis in ir.py): an assignment whose
     value is never read is deleted, provided its right-hand side can't fail
     or have side effects (a constant, a list of constants, a variable that is
     surely assigned).
  4. A peephole pass on the bytecode: constant branches, jump threading,
     jumps to the next instruction, unreachable code, and tail calls.

The passes feed each other: after `x = 10; y = x * 2; print y;` propagation turns
the reads into 10 and 20, folding computes x * 2, and then x and y are never
read, so both stores are dead and the whole program becomes PUSH 20; PRINT.

The one deliberate change in behaviour is tail-call optimization: `return f(...)`
reuses the current call's frame (TAIL_CALL), so tail recursion no longer runs
into the call-depth limit. Every other program behaves exactly as unoptimized.
"""

from ast_nodes import (ArrayLit, Assign, BinOp, Block, Call, ExprStmt, For, FuncDef,
                       If, Index, IndexAssign, LogicalOp, Number, Print, Program,
                       Return, UnaryOp, Var, While)
from compiler import BINARY_OPCODES, Instruction, compile_program
from ir import constant_reads, removable_stores
from vm import apply_binary

JUMPS = {"JUMP", "JUMP_IF_FALSE"}
HAS_TARGET = JUMPS | {"CALL", "TAIL_CALL"}  # instructions whose arg is a code address
MAX_DSE_ROUNDS = 10


# ======================= Pass 2: AST constant folding =======================

def fold_constants(node, constants=None):
    """Return a new AST where constant sub-expressions are pre-computed.

    constants: optional {id(Var node): value} from constant propagation; those
    variable reads are treated as literals.
    """
    return Folder(constants or {}).fold(node)


class Folder:
    def __init__(self, constants, dead=frozenset()):
        self.constants = constants
        self.dead = dead   # id(Assign node) of dead stores to delete

    def statements(self, statements):
        return [s for s in map(self.fold, statements) if s is not None]

    def fold(self, node):
        if node is None:
            return None
        f = self.fold
        if isinstance(node, Program):
            return Program(self.statements(node.statements), line=node.line)
        if isinstance(node, Block):
            return Block(self.statements(node.statements), line=node.line)
        if isinstance(node, FuncDef):
            return FuncDef(node.name, node.params, f(node.body), line=node.line)
        if isinstance(node, Assign):
            if id(node) in self.dead:
                return None
            return Assign(node.name, f(node.value), line=node.line)
        if isinstance(node, Print):
            return Print(f(node.value), line=node.line)
        if isinstance(node, Return):
            return Return(f(node.value), line=node.line)
        if isinstance(node, ExprStmt):
            return ExprStmt(f(node.expr), line=node.line)
        if isinstance(node, If):
            return If(f(node.condition), f(node.then_body), f(node.else_body), line=node.line)
        if isinstance(node, While):
            return While(f(node.condition), f(node.body), line=node.line)
        if isinstance(node, For):
            return For(f(node.init), f(node.condition), f(node.update), f(node.body), line=node.line)
        if isinstance(node, Call):
            return Call(node.name, [f(a) for a in node.args], line=node.line)
        if isinstance(node, ArrayLit):
            return ArrayLit([f(item) for item in node.items], line=node.line)
        if isinstance(node, Index):
            return Index(f(node.target), f(node.index), line=node.line)
        if isinstance(node, IndexAssign):
            return IndexAssign(f(node.target), f(node.index), f(node.value), line=node.line)
        if isinstance(node, Var):
            if id(node) in self.constants:   # proven constant by data-flow analysis
                return Number(self.constants[id(node)], line=node.line)
            return node
        if isinstance(node, BinOp):
            return self.binop(node)
        if isinstance(node, UnaryOp):
            return self.unary(node)
        if isinstance(node, LogicalOp):
            return self.logical(node)
        return node  # Number, Break, Continue: nothing to fold

    def binop(self, node):
        left, right = self.fold(node.left), self.fold(node.right)
        opcode = BINARY_OPCODES[node.op]
        if isinstance(left, Number) and isinstance(right, Number):
            # Leave x / 0 and x % 0 alone so the VM still raises the error at runtime, with its line.
            if not (opcode in ("DIV", "MOD") and right.value == 0):
                return Number(apply_binary(opcode, left.value, right.value), line=node.line)
        return BinOp(node.op, left, right, line=node.line)

    def unary(self, node):
        operand = self.fold(node.operand)
        if isinstance(operand, Number):
            value = -operand.value if node.op == "-" else (1 if operand.value == 0 else 0)
            return Number(value, line=node.line)
        return UnaryOp(node.op, operand, line=node.line)

    def logical(self, node):
        left, right = self.fold(node.left), self.fold(node.right)
        if isinstance(left, Number):
            # The left side alone decides: the right side (even a call) would never run anyway.
            if node.op == "and" and left.value == 0:
                return Number(0, line=node.line)
            if node.op == "or" and left.value != 0:
                return Number(1, line=node.line)
            # Otherwise the result is just the truthiness of the right side.
            if isinstance(right, Number):
                return Number(1 if right.value != 0 else 0, line=node.line)
        return LogicalOp(node.op, left, right, line=node.line)


# ===================== Pass 3: dead-store elimination =======================

def remove_dead_stores(tree):
    """Delete assignments whose value is never read (see ir.IR.removable).

    Repeats, because deleting `y = x` can leave the earlier `x = [1]` dead too.
    """
    for _ in range(MAX_DSE_ROUNDS):
        dead = removable_stores(tree)
        if not dead:
            break
        tree = Folder({}, dead).fold(tree)
    return tree


# ========================= Pass 4: bytecode peephole ========================

def peephole(code):
    """Return optimized bytecode. Repeats the sub-passes until nothing changes."""
    code = [Instruction(i.op, i.arg, i.line, i.label) for i in code]  # don't mutate input
    changed = True
    while changed:
        changed = False
        for sub_pass in (_resolve_constant_branches, _thread_jumps, _tail_calls,
                         _remove_jumps_to_next, _remove_unreachable):
            code, did_change = sub_pass(code)
            changed = changed or did_change
    return code


def _compact(code, keep):
    """Drop instructions where keep[i] is False and fix up every jump/call target.

    A jump to a removed instruction is redirected to the next surviving one,
    which is exactly where execution would have fallen through to. A removed
    function-entry label moves to that same instruction.
    """
    new_addr = []
    count = 0
    for k in keep:
        new_addr.append(count)
        count += k
    new_addr.append(count)  # an address one past the end stays one past the end
    result = []
    carried_label = None
    for ins, k in zip(code, keep):
        if not k:
            carried_label = ins.label or carried_label
            continue
        if ins.op in HAS_TARGET:
            ins.arg = new_addr[ins.arg]
        if carried_label and not ins.label:
            ins.label = carried_label
        carried_label = None
        result.append(ins)
    return result


def _resolve_constant_branches(code):
    """A constant that goes straight into JUMP_IF_FALSE decides the branch now.

        PUSH c ; JUMP_IF_FALSE t             (possibly with JUMPs in between)
        ->  JUMP t          if c == 0
        ->  JUMP past it    otherwise

    The PUSH is replaced in place, so other paths that reach the
    JUMP_IF_FALSE are unaffected; if nothing else reaches it, dead-code
    removal deletes it later. This handles `if 0`, `while 1`, and the
    PUSH 1 / PUSH 0 that `and` / `or` leave behind inside conditions.
    """
    changed = False
    for i, ins in enumerate(code):
        if ins.op != "PUSH":
            continue
        j, seen = i + 1, set()
        while j < len(code) and code[j].op == "JUMP" and j not in seen:
            seen.add(j)
            j = code[j].arg
        if j < len(code) and code[j].op == "JUMP_IF_FALSE":
            dest = code[j].arg if ins.arg == 0 else j + 1
            code[i] = Instruction("JUMP", dest, ins.line, ins.label)
            changed = True
    return code, changed


def _thread_jumps(code):
    """A jump whose target is another JUMP goes straight to the final target."""
    changed = False
    for ins in code:
        if ins.op not in JUMPS:
            continue
        target, seen = ins.arg, set()
        while target < len(code) and code[target].op == "JUMP" and target not in seen:
            seen.add(target)  # guards against JUMP cycles like `while 1 {}`
            target = code[target].arg
        if target != ins.arg:
            ins.arg = target
            changed = True
    return code, changed


def _tail_calls(code):
    """CALL f followed by RET (possibly via JUMPs) becomes TAIL_CALL f.

    `return f(x);` has nothing left to do after f returns, so f can reuse the
    caller's frame: its RET then goes straight back to our caller. Recursion
    in tail position runs in a constant number of frames. The old RET stays in
    place for any other path that jumps to it; if none does, it is unreachable
    and gets removed.
    """
    changed = False
    for i, ins in enumerate(code):
        if ins.op != "CALL":
            continue
        j, seen = i + 1, set()
        while j < len(code) and code[j].op == "JUMP" and j not in seen:
            seen.add(j)
            j = code[j].arg
        if j < len(code) and code[j].op == "RET":
            code[i] = Instruction("TAIL_CALL", ins.arg, ins.line, ins.label)
            changed = True
    return code, changed


def _remove_jumps_to_next(code):
    """A JUMP to the very next instruction does nothing."""
    keep = [not (ins.op == "JUMP" and ins.arg == i + 1) for i, ins in enumerate(code)]
    changed = not all(keep)
    return (_compact(code, keep) if changed else code), changed


def _remove_unreachable(code):
    """Walk the control flow from address 0 and drop anything never reached.

    Functions are only reachable through a CALL, so a function that is never
    called disappears too.
    """
    reachable = set()
    work = [0]
    while work:
        i = work.pop()
        if i in reachable or i >= len(code):
            continue
        reachable.add(i)
        ins = code[i]
        if ins.op in ("JUMP", "TAIL_CALL"):   # neither ever falls through
            work.append(ins.arg)
        elif ins.op not in ("HALT", "RET"):
            work.append(i + 1)  # includes CALL: execution resumes here after RET
            if ins.op in ("JUMP_IF_FALSE", "CALL"):
                work.append(ins.arg)
    keep = [i in reachable for i in range(len(code))]
    changed = not all(keep)
    return (_compact(code, keep) if changed else code), changed


def optimize(program, propagate=True):
    """Full optimizing compile: propagate and fold constants, delete dead stores,
    generate code, then peephole it. propagate=False skips both data-flow passes."""
    # Compile the original tree once first, only for its checks: folding can
    # remove code (e.g. `0 and missing()`), and a semantic error there must
    # still be reported exactly as it is without the optimizer.
    compile_program(program)
    if not propagate:
        return peephole(compile_program(fold_constants(program)))
    tree = fold_constants(program, constant_reads(program))
    tree = remove_dead_stores(tree)
    return peephole(compile_program(tree))
