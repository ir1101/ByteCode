"""Optimizer: constant folding on the AST, then a peephole pass on the bytecode.

Both passes preserve behaviour exactly: same printed output, same errors.
"""

from ast_nodes import (Assign, BinOp, Block, Call, ExprStmt, For, FuncDef, If,
                       LogicalOp, Number, Print, Program, Return, UnaryOp, While)
from compiler import BINARY_OPCODES, Instruction, compile_program
from vm import apply_binary

JUMPS = {"JUMP", "JUMP_IF_FALSE"}
HAS_TARGET = JUMPS | {"CALL"}  # instructions whose arg is a code address


# ======================= Pass 1: AST constant folding =======================

def _fold_optional(node):
    return None if node is None else fold_constants(node)


def fold_constants(node):
    """Return a new AST where constant sub-expressions are pre-computed."""
    if isinstance(node, Program):
        return Program([fold_constants(s) for s in node.statements], line=node.line)
    if isinstance(node, Block):
        return Block([fold_constants(s) for s in node.statements], line=node.line)
    if isinstance(node, FuncDef):
        return FuncDef(node.name, node.params, fold_constants(node.body), line=node.line)
    if isinstance(node, Assign):
        return Assign(node.name, fold_constants(node.value), line=node.line)
    if isinstance(node, Print):
        return Print(fold_constants(node.value), line=node.line)
    if isinstance(node, Return):
        return Return(_fold_optional(node.value), line=node.line)
    if isinstance(node, ExprStmt):
        return ExprStmt(fold_constants(node.expr), line=node.line)
    if isinstance(node, If):
        return If(fold_constants(node.condition), fold_constants(node.then_body),
                  _fold_optional(node.else_body), line=node.line)
    if isinstance(node, While):
        return While(fold_constants(node.condition), fold_constants(node.body), line=node.line)
    if isinstance(node, For):
        return For(_fold_optional(node.init), _fold_optional(node.condition),
                   _fold_optional(node.update), fold_constants(node.body), line=node.line)
    if isinstance(node, Call):
        return Call(node.name, [fold_constants(a) for a in node.args], line=node.line)
    if isinstance(node, BinOp):
        return _fold_binop(node)
    if isinstance(node, UnaryOp):
        return _fold_unary(node)
    if isinstance(node, LogicalOp):
        return _fold_logical(node)
    return node  # Number, Var, Break, Continue: nothing to fold


def _fold_binop(node):
    left, right = fold_constants(node.left), fold_constants(node.right)
    opcode = BINARY_OPCODES[node.op]
    if isinstance(left, Number) and isinstance(right, Number):
        # Leave x / 0 alone so the VM still raises the error at runtime, with its line.
        if not (opcode == "DIV" and right.value == 0):
            return Number(apply_binary(opcode, left.value, right.value), line=node.line)
    return BinOp(node.op, left, right, line=node.line)


def _fold_unary(node):
    operand = fold_constants(node.operand)
    if isinstance(operand, Number):
        value = -operand.value if node.op == "-" else (1 if operand.value == 0 else 0)
        return Number(value, line=node.line)
    return UnaryOp(node.op, operand, line=node.line)


def _fold_logical(node):
    left, right = fold_constants(node.left), fold_constants(node.right)
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


# ========================= Pass 2: bytecode peephole ========================

def peephole(code):
    """Return optimized bytecode. Repeats the sub-passes until nothing changes."""
    code = [Instruction(i.op, i.arg, i.line, i.label) for i in code]  # don't mutate input
    changed = True
    while changed:
        changed = False
        for sub_pass in (_resolve_constant_branches, _thread_jumps,
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
        if ins.op == "JUMP":
            work.append(ins.arg)
        elif ins.op not in ("HALT", "RET"):
            work.append(i + 1)  # includes CALL: execution resumes here after RET
            if ins.op in ("JUMP_IF_FALSE", "CALL"):
                work.append(ins.arg)
    keep = [i in reachable for i in range(len(code))]
    changed = not all(keep)
    return (_compact(code, keep) if changed else code), changed


def optimize(program):
    """Full optimizing compile: fold the AST, generate code, then peephole it."""
    # Compile the original tree once first, only for its checks: folding can
    # remove code (e.g. `0 and missing()`), and a semantic error there must
    # still be reported exactly as it is without the optimizer.
    compile_program(program)
    return peephole(compile_program(fold_constants(program)))
