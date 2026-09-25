"""Compiler: walks the AST and emits bytecode for the stack VM.

Instruction set ([arg] where one is taken):
    PUSH [int]            push a constant
    LOAD [name]           push a variable (current function's locals, then globals)
    STORE [name]          pop into a variable (locals inside a function, else globals)
    POP                   discard the top of stack (result of a call used as a statement)
    ADD SUB MUL DIV       pop b, pop a, push (a op b)
    EQ NE LT GT LE GE     pop b, pop a, push 1 if true else 0
    NEG                   negate the top of stack
    NOT                   replace top with 1 if it is 0, else 0
    JUMP [addr]           unconditional jump
    JUMP_IF_FALSE [addr]  pop; jump if the value is 0
    CALL [addr]           push a new frame (remembering where to return) and jump to addr
    RET                   pop the return value, drop the frame, jump back, push the value
    PRINT                 pop and print
    HALT                  stop execution

Layout: top-level code first, then HALT, then each function body. A function
starts by STOREing its arguments (last argument first, since it is on top of
the stack) and always ends with an implicit `PUSH 0; RET`.
"""

from ast_nodes import FuncDef
from errors import CompileError

BINARY_OPCODES = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV",
    "==": "EQ", "!=": "NE", "<": "LT", ">": "GT", "<=": "LE", ">=": "GE",
}


class Instruction:
    def __init__(self, op, arg=None, line=None, label=None):
        self.op = op
        self.arg = arg
        self.line = line    # source line, used for runtime error messages
        self.label = label  # function name/signature on a function's first instruction

    def __repr__(self):
        return self.op if self.arg is None else f"{self.op} {self.arg}"

    def __eq__(self, other):
        return isinstance(other, Instruction) and (self.op, self.arg) == (other.op, other.arg)


class Loop:
    """Jumps emitted by break/continue inside one loop, patched when the loop ends."""

    def __init__(self):
        self.breaks = []
        self.continues = []


class Compiler:
    def __init__(self):
        self.code = []
        self.functions = {}       # name -> FuncDef, collected before any code is emitted
        self.function_addr = {}   # name -> address of the function's first instruction
        self.pending_calls = []   # (address of CALL, function name), patched at the end
        self.loops = []           # innermost loop last
        self.current_function = None

    def emit(self, op, arg=None, line=None):
        self.code.append(Instruction(op, arg, line))
        return len(self.code) - 1  # address of the emitted instruction

    def patch(self, addr, target):
        """Back-patch a jump that was emitted before its target was known."""
        self.code[addr].arg = target

    def here(self):
        return len(self.code)

    def compile(self, program):
        # Pass 1: collect every function first, so calls may appear before the
        # definition (and functions may call each other: mutual recursion).
        for stmt in program.statements:
            if isinstance(stmt, FuncDef):
                self.declare_function(stmt)

        # Pass 2: top-level code, then HALT, then the function bodies.
        for stmt in program.statements:
            if not isinstance(stmt, FuncDef):
                self.visit(stmt)
        self.emit("HALT")
        for fn in self.functions.values():
            self.compile_function(fn)

        for addr, name in self.pending_calls:
            self.patch(addr, self.function_addr[name])
        return self.code

    def declare_function(self, fn):
        if fn.name in self.functions:
            first = self.functions[fn.name].line
            raise CompileError(f"function '{fn.name}' is already defined on line {first}", fn.line)
        seen = set()
        for param in fn.params:
            if param in seen:
                raise CompileError(f"duplicate parameter '{param}' in function '{fn.name}'", fn.line)
            seen.add(param)
        self.functions[fn.name] = fn

    def compile_function(self, fn):
        entry = self.here()
        self.function_addr[fn.name] = entry
        self.current_function, self.loops = fn, []
        for param in reversed(fn.params):  # the last argument is on top of the stack
            self.emit("STORE", param, fn.line)
        self.visit(fn.body)
        self.emit("PUSH", 0, fn.line)      # falling off the end returns 0
        self.emit("RET", line=fn.line)
        self.code[entry].label = f"{fn.name}({', '.join(fn.params)})"
        self.current_function = None

    def visit(self, node):
        method = getattr(self, "visit_" + type(node).__name__, None)
        if method is None:
            raise CompileError(f"no code generator for {type(node).__name__}", node.line)
        method(node)

    # ----- statements -----
    def visit_Block(self, node):
        for stmt in node.statements:
            self.visit(stmt)

    def visit_Assign(self, node):
        self.visit(node.value)
        self.emit("STORE", node.name, node.line)

    def visit_Print(self, node):
        self.visit(node.value)
        self.emit("PRINT", line=node.line)

    def visit_ExprStmt(self, node):
        self.visit(node.expr)
        self.emit("POP", line=node.line)  # the call's return value is not used

    def visit_If(self, node):
        self.visit(node.condition)
        jump_to_else = self.emit("JUMP_IF_FALSE", None, node.line)
        self.visit(node.then_body)
        if node.else_body is None:
            self.patch(jump_to_else, self.here())
        else:
            jump_to_end = self.emit("JUMP", None, node.line)
            self.patch(jump_to_else, self.here())
            self.visit(node.else_body)
            self.patch(jump_to_end, self.here())

    def visit_While(self, node):
        loop_start = self.here()
        self.visit(node.condition)
        jump_to_end = self.emit("JUMP_IF_FALSE", None, node.line)
        loop = self.loop_body(node.body)
        self.emit("JUMP", loop_start, node.line)
        self.patch(jump_to_end, self.here())
        self.finish_loop(loop, continue_target=loop_start, end=self.here())

    def visit_For(self, node):
        # init; start: cond; JIF end; body; next: update; JUMP start; end:
        if node.init is not None:
            self.visit(node.init)
        loop_start = self.here()
        jump_to_end = None
        if node.condition is not None:  # a missing condition means "loop forever"
            self.visit(node.condition)
            jump_to_end = self.emit("JUMP_IF_FALSE", None, node.line)
        loop = self.loop_body(node.body)
        continue_target = self.here()   # `continue` must still run the update
        if node.update is not None:
            self.visit(node.update)
        self.emit("JUMP", loop_start, node.line)
        if jump_to_end is not None:
            self.patch(jump_to_end, self.here())
        self.finish_loop(loop, continue_target=continue_target, end=self.here())

    def loop_body(self, body):
        loop = Loop()
        self.loops.append(loop)
        self.visit(body)
        self.loops.pop()
        return loop

    def finish_loop(self, loop, continue_target, end):
        for addr in loop.breaks:
            self.patch(addr, end)
        for addr in loop.continues:
            self.patch(addr, continue_target)

    def visit_Break(self, node):
        if not self.loops:
            raise CompileError("'break' outside a loop", node.line)
        self.loops[-1].breaks.append(self.emit("JUMP", None, node.line))

    def visit_Continue(self, node):
        if not self.loops:
            raise CompileError("'continue' outside a loop", node.line)
        self.loops[-1].continues.append(self.emit("JUMP", None, node.line))

    def visit_Return(self, node):
        if self.current_function is None:
            raise CompileError("'return' outside a function", node.line)
        if node.value is None:
            self.emit("PUSH", 0, node.line)
        else:
            self.visit(node.value)
        self.emit("RET", line=node.line)

    def visit_FuncDef(self, node):
        raise CompileError("functions can only be defined at the top level", node.line)

    # ----- expressions -----
    def visit_Number(self, node):
        self.emit("PUSH", node.value, node.line)

    def visit_Var(self, node):
        self.emit("LOAD", node.name, node.line)

    def visit_BinOp(self, node):
        self.visit(node.left)
        self.visit(node.right)
        self.emit(BINARY_OPCODES[node.op], line=node.line)

    def visit_UnaryOp(self, node):
        self.visit(node.operand)
        self.emit("NEG" if node.op == "-" else "NOT", line=node.line)

    def visit_Call(self, node):
        fn = self.functions.get(node.name)
        if fn is None:
            raise CompileError(f"undefined function '{node.name}'", node.line)
        if len(node.args) != len(fn.params):
            raise CompileError(f"function '{node.name}' takes {len(fn.params)} argument(s), "
                               f"but {len(node.args)} were given", node.line)
        for arg in node.args:  # left to right, so the last argument ends up on top
            self.visit(arg)
        self.pending_calls.append((self.emit("CALL", None, node.line), node.name))

    def visit_LogicalOp(self, node):
        """Short-circuit and/or. The result is always normalised to 0 or 1."""
        line = node.line
        if node.op == "and":
            # left; JIF F; right; JIF F; PUSH 1; JUMP END; F: PUSH 0; END:
            self.visit(node.left)
            left_false = self.emit("JUMP_IF_FALSE", None, line)
            self.visit(node.right)
            right_false = self.emit("JUMP_IF_FALSE", None, line)
            self.emit("PUSH", 1, line)
            to_end = self.emit("JUMP", None, line)
            self.patch(left_false, self.here())
            self.patch(right_false, self.here())
            self.emit("PUSH", 0, line)
            self.patch(to_end, self.here())
        else:
            # left; JIF R; PUSH 1; JUMP END; R: right; JIF F; PUSH 1; JUMP END; F: PUSH 0; END:
            self.visit(node.left)
            try_right = self.emit("JUMP_IF_FALSE", None, line)
            self.emit("PUSH", 1, line)
            end_a = self.emit("JUMP", None, line)
            self.patch(try_right, self.here())
            self.visit(node.right)
            right_false = self.emit("JUMP_IF_FALSE", None, line)
            self.emit("PUSH", 1, line)
            end_b = self.emit("JUMP", None, line)
            self.patch(right_false, self.here())
            self.emit("PUSH", 0, line)
            self.patch(end_a, self.here())
            self.patch(end_b, self.here())


def compile_program(program):
    return Compiler().compile(program)


def disassemble(code):
    """Return a numbered, human-readable listing of the bytecode."""
    lines = []
    for addr, ins in enumerate(code):
        if ins.label:
            lines.append(f"      {ins.label}:")
        arg = "" if ins.arg is None else str(ins.arg)
        src = "" if ins.line is None else f"; line {ins.line}"
        if ins.op == "CALL" and isinstance(ins.arg, int) and ins.arg < len(code) and code[ins.arg].label:
            src += f"  -> {code[ins.arg].label}"
        lines.append(f"{addr:04d}  {ins.op:<14}{arg:<8}{src}".rstrip())
    return "\n".join(lines)
