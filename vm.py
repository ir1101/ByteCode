"""Stack-based virtual machine that executes MiniLang bytecode."""

import sys

from errors import VMError

BINARY_OPS = {"ADD", "SUB", "MUL", "DIV", "MOD", "EQ", "NE", "LT", "GT", "LE", "GE"}
SYMBOLS = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%",
           "LT": "<", "GT": ">", "LE": "<=", "GE": ">="}


def type_name(value):
    return "a list" if isinstance(value, list) else "a number"


def _trunc_div(a, b):
    """Integer division that rounds toward zero (like C/Java), not Python's floor."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def apply_binary(op, a, b, line=None):
    """Compute a binary opcode. Shared with the optimizer so folding matches runtime."""
    if op == "EQ":
        return int(a == b)  # == and != also compare lists, item by item
    if op == "NE":
        return int(a != b)
    if isinstance(a, list) or isinstance(b, list):
        raise VMError(f"'{SYMBOLS[op]}' needs two numbers, not {type_name(a)} and {type_name(b)}", line)
    if op == "ADD":
        return a + b
    if op == "SUB":
        return a - b
    if op == "MUL":
        return a * b
    if op == "DIV":
        if b == 0:
            raise VMError("division by zero", line)
        return _trunc_div(a, b)
    if op == "MOD":
        if b == 0:
            raise VMError("modulo by zero", line)
        return a - b * _trunc_div(a, b)  # sign follows a, so a == (a / b) * b + a % b
    return int({"LT": a < b, "GT": a > b, "LE": a <= b, "GE": a >= b}[op])


class Frame:
    """One active function call: its own local variables and where to return to."""

    __slots__ = ("name", "return_addr", "locals")

    def __init__(self, name, return_addr):
        self.name = name
        self.return_addr = return_addr
        self.locals = {}


class VM:
    def __init__(self, code, out=None, max_steps=10_000_000, max_output_lines=None,
                 max_call_depth=1000, on_step=None):
        self.code = code
        self.stack = []      # operand stack, shared by all calls
        self.variables = {}  # globals
        self.frames = []     # call stack; empty while running top-level code
        self.pc = 0  # program counter: index of the next instruction
        self.out = out if out is not None else sys.stdout
        self.max_steps = max_steps  # guard against runaway loops
        self.max_output_lines = max_output_lines  # guard against runaway printing
        self.max_call_depth = max_call_depth  # guard against runaway recursion
        self.lines_printed = 0
        # Called as on_step(addr, instruction, vm) after each instruction runs.
        self.on_step = on_step

    def pop(self, ins):
        if not self.stack:
            raise VMError("stack underflow", ins.line)
        return self.stack.pop()

    def pop_number(self, ins, what):
        value = self.pop(ins)
        if isinstance(value, list):
            raise VMError(f"{what} must be a number, not a list", ins.line)
        return value

    def pop_list(self, ins, what):
        value = self.pop(ins)
        if not isinstance(value, list):
            raise VMError(f"{what} must be a list, not a number", ins.line)
        return value

    def check_index(self, lst, index, ins):
        if isinstance(index, list):
            raise VMError("a list index must be a number, not a list", ins.line)
        if not 0 <= index < len(lst):
            raise VMError(f"index {index} is out of range for a list of length {len(lst)}", ins.line)

    def current_scope(self):
        """Where STORE writes: the current call's locals, or globals at top level."""
        return self.frames[-1].locals if self.frames else self.variables

    def load(self, name, ins):
        if self.frames and name in self.frames[-1].locals:
            return self.frames[-1].locals[name]
        if name in self.variables:
            return self.variables[name]
        raise VMError(f"undefined variable '{name}'", ins.line)

    def run(self):
        steps = 0
        while self.pc < len(self.code):
            addr = self.pc
            ins = self.code[addr]
            self.pc += 1
            steps += 1
            if steps > self.max_steps:
                raise VMError(f"step limit of {self.max_steps} exceeded (infinite loop?)", ins.line)

            op = ins.op
            if op == "PUSH":
                self.stack.append(ins.arg)
            elif op == "LOAD":
                self.stack.append(self.load(ins.arg, ins))
            elif op == "STORE":
                self.current_scope()[ins.arg] = self.pop(ins)
            elif op == "POP":
                self.pop(ins)
            elif op in BINARY_OPS:
                b = self.pop(ins)
                a = self.pop(ins)
                self.stack.append(apply_binary(op, a, b, ins.line))
            elif op == "NEG":
                self.stack.append(-self.pop_number(ins, "the operand of '-'"))
            elif op == "NOT":
                self.stack.append(1 if self.pop_number(ins, "the operand of 'not'") == 0 else 0)
            elif op == "JUMP":
                self.pc = ins.arg
            elif op == "JUMP_IF_FALSE":
                if self.pop_number(ins, "a condition") == 0:
                    self.pc = ins.arg
            elif op == "BUILD_LIST":
                items = self.stack[len(self.stack) - ins.arg:] if ins.arg else []
                del self.stack[len(self.stack) - ins.arg:]
                self.stack.append(items)
            elif op == "INDEX":
                index = self.pop(ins)
                lst = self.pop_list(ins, "the value being indexed")
                self.check_index(lst, index, ins)
                self.stack.append(lst[index])
            elif op == "STORE_INDEX":
                value = self.pop(ins)
                index = self.pop(ins)
                lst = self.pop_list(ins, "the value being indexed")
                self.check_index(lst, index, ins)
                lst[index] = value
            elif op == "LEN":
                self.stack.append(len(self.pop_list(ins, "the argument of len()")))
            elif op == "APPEND":
                value = self.pop(ins)
                lst = self.pop_list(ins, "the first argument of append()")
                lst.append(value)
                self.stack.append(len(lst))
            elif op == "CALL":
                if len(self.frames) >= self.max_call_depth:
                    raise VMError(f"maximum call depth of {self.max_call_depth} exceeded "
                                  "(infinite recursion?)", ins.line)
                target = self.code[ins.arg]
                self.frames.append(Frame(target.label or "?", return_addr=self.pc))
                self.pc = ins.arg
            elif op == "RET":
                if not self.frames:
                    raise VMError("return outside a function", ins.line)
                value = self.pop(ins)
                self.pc = self.frames.pop().return_addr
                self.stack.append(value)
            elif op == "PRINT":
                if self.max_output_lines is not None and self.lines_printed >= self.max_output_lines:
                    raise VMError(f"output limit of {self.max_output_lines} lines exceeded", ins.line)
                print(self.pop(ins), file=self.out)
                self.lines_printed += 1
            elif op == "HALT":
                self.pc = len(self.code)
            else:
                raise VMError(f"unknown opcode {op}", ins.line)

            if self.on_step is not None:
                self.on_step(addr, ins, self)


def text_tracer(stream):
    """Return an on_step hook that writes one readable line per instruction."""
    def trace(addr, ins, vm):
        arg = "" if ins.arg is None else str(ins.arg)
        src = "" if ins.line is None else f"; line {ins.line}"
        stack = f"stack={vm.stack}"
        where = f"  in {vm.frames[-1].name} (depth {len(vm.frames)})" if vm.frames else ""
        print(f"[{addr:04d}] {ins.op:<14}{arg:<8}{stack:<24}{src}{where}".rstrip(), file=stream)
    return trace
