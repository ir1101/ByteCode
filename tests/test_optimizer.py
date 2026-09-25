import os
import unittest

from tests.helpers import ROOT, compile_source, run_source
from ast_nodes import Assign, BinOp, LogicalOp, Number, Print, Var
from compiler import Instruction as I
from errors import MiniLangError, VMError
from lexer import tokenize
from optimizer import JUMPS, fold_constants, peephole
from parser import parse

EXAMPLES = ("demo.ml", "optimize.ml", "functions.ml")


def folded(source):
    return fold_constants(parse(tokenize(source))).statements


class ConstantFoldingTests(unittest.TestCase):
    def test_arithmetic_is_folded(self):
        self.assertEqual(folded("x = 1 + 2 * 3;"), [Assign("x", Number(7))])

    def test_division_folds_with_vm_semantics(self):
        self.assertEqual(folded("print -7 / 2;"), [Print(Number(-3))])

    def test_not_and_comparisons_fold_to_0_or_1(self):
        self.assertEqual(folded("print not 0; print 3 > 5;"), [Print(Number(1)), Print(Number(0))])

    def test_logic_folds_when_left_side_decides(self):
        self.assertEqual(folded("print 0 and y; print 7 or y;"), [Print(Number(0)), Print(Number(1))])

    def test_logic_kept_when_result_depends_on_variable(self):
        self.assertEqual(folded("print 1 and y;"), [Print(LogicalOp("and", Number(1), Var("y")))])

    def test_partial_folding_inside_variable_expression(self):
        self.assertEqual(folded("print x + 2 * 3;"), [Print(BinOp("+", Var("x"), Number(6)))])

    def test_division_by_zero_is_not_folded(self):
        self.assertEqual(folded("print 1 / 0;"), [Print(BinOp("/", Number(1), Number(0)))])
        with self.assertRaises(VMError) as cm:
            run_source("x = 1;\nprint 1 / 0;", optimize=True)
        self.assertEqual(cm.exception.line, 2)

    def test_original_tree_is_not_modified(self):
        tree = parse(tokenize("print 1 + 2;"))
        fold_constants(tree)
        self.assertEqual(tree.statements, [Print(BinOp("+", Number(1), Number(2)))])


class PeepholeTests(unittest.TestCase):
    def test_if_0_keeps_only_else_branch(self):
        code = compile_source("if 0 { print 1; } else { print 2; }", optimize=True)
        self.assertEqual(code, [I("PUSH", 2), I("PRINT"), I("HALT")])

    def test_while_0_disappears(self):
        self.assertEqual(compile_source("while 0 { print 1; }", optimize=True), [I("HALT")])

    def test_while_1_drops_its_condition_check(self):
        code = compile_source("while 1 { print 1; }", optimize=True)
        self.assertEqual(code, [I("PUSH", 1), I("PRINT"), I("JUMP", 0)])

    def test_and_or_conditions_become_direct_jumps(self):
        # No PUSH 1 / PUSH 0 result values survive: the branches jump directly.
        for src in ("if a and b { print 1; }", "if a or b { print 1; }",
                    "while a and b { a = a - b; }"):
            with self.subTest(src=src):
                code = compile_source(src, optimize=True)
                pushes = [ins.arg for ins in code if ins.op == "PUSH"]
                self.assertNotIn(0, pushes)
                self.assertEqual(pushes.count(1), src.count("print 1"))

    def test_jump_threading(self):
        code = [
            I("LOAD", "x"),            # 0
            I("JUMP_IF_FALSE", 5),     # 1 -> 5, which is a JUMP to 0
            I("LOAD", "x"),            # 2
            I("PRINT"),                # 3
            I("HALT"),                 # 4
            I("JUMP", 0),              # 5 (unreachable once threaded)
        ]
        self.assertEqual(peephole(code), [
            I("LOAD", "x"), I("JUMP_IF_FALSE", 0), I("LOAD", "x"), I("PRINT"), I("HALT"),
        ])

    def test_dead_code_and_jump_to_next_removed(self):
        code = [
            I("JUMP", 1),    # 0 -> JUMP -> threaded to 3, then becomes jump-to-next
            I("JUMP", 3),    # 1
            I("PUSH", 99),   # 2 never reached
            I("PUSH", 5),    # 3
            I("PRINT"),      # 4
            I("HALT"),       # 5
        ]
        self.assertEqual(peephole(code), [I("PUSH", 5), I("PRINT"), I("HALT")])

    def test_uncalled_function_is_removed(self):
        code = compile_source("func used() { return 1; }\nfunc unused() { return 2; }\nprint used();",
                              optimize=True)
        self.assertEqual(code, [I("CALL", 3), I("PRINT"), I("HALT"), I("PUSH", 1), I("RET")])
        self.assertEqual(code[3].label, "used()")

    def test_code_after_return_is_removed(self):
        code = compile_source("func f() { return 1; print 2; }\nprint f();", optimize=True)
        self.assertNotIn(I("PUSH", 2), code)
        self.assertNotIn(I("PUSH", 0), code)  # the implicit "return 0" is unreachable too

    def test_function_label_survives_when_entry_is_removed(self):
        # The body starts with `if 1`, whose check is optimized away entirely.
        code = compile_source("func f() { if 1 { return 5; } return 6; }\nprint f();", optimize=True)
        entry = code[0].arg
        self.assertEqual(code[entry].label, "f()")
        self.assertEqual(code[entry:], [I("PUSH", 5), I("RET")])

    def test_input_bytecode_is_not_modified(self):
        code = [I("JUMP", 1), I("HALT")]
        peephole(code)
        self.assertEqual(code, [I("JUMP", 1), I("HALT")])

    def test_optimized_code_has_no_leftover_patterns(self):
        for name in EXAMPLES:
            with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as f:
                code = compile_source(f.read(), optimize=True)
            for i, ins in enumerate(code):
                if ins.op in JUMPS:
                    self.assertNotEqual(code[ins.arg].op, "JUMP", f"{name}: unthreaded jump at {i}")
                if ins.op == "JUMP":
                    self.assertNotEqual(ins.arg, i + 1, f"{name}: jump-to-next at {i}")


class SameBehaviourTests(unittest.TestCase):
    """The optimizer must never change what a program prints or which error it raises."""

    PROGRAMS = [
        "x = 5; while x > 0 { print x; x = x - 2; }",
        "a = 3; b = 0; print a and b; print a or b; print not a; print b or 0 or 7;",
        "if 1 and 0 { print 1; } else if 2 > 1 { print 2; } else { print 3; }",
        "x = 1; if not 0 { x = 10; } print x * -3 / 4;",
        "while 0 { print 1; } print 2;",
        "x = 0; while x < 3 { if x == 1 { print 10; } else { print 0; } x = x + 1; }",
        "print (1 + 2) * (3 - 4) / 2 == -1;",
        "i = 0; while 1 { i = i + 1; if i == 4 { print i; x = 1 / 0; } }",
        "x = 1;\nprint 2 / (x - 1);",
        "print 1;\nprint y;",
        "a = 1; b = 0; if a and b { print 1; } else { print 2; } if a or b { print 3; }",
        "a = 0; b = 5; if a or b > 4 and not a { print 4; } else { print 5; }",
        "a = 1; b = 0; while a and b < 3 { b = b + 1; print b; } print not (a and b);",
        "x = 0; if x or 1 / x { print 6; }",
        # functions, recursion, for, break/continue
        "func fact(n) { if n <= 1 { return 1; } return n * fact(n - 1); } print fact(6);",
        "func f(a, b) { if a > b { return a - b; } return b - a; } print f(3, 10); print f(10, 3);",
        "func g() { for i = 0; i < 10; i = i + 1 { if i == 4 { return i * 2; } } } print g();",
        "func h() { while 1 { return 3; } } print h();",
        "for i = 0; i < 6; i = i + 1 { if i == 1 or i == 3 { continue; } if i > 4 { break; } print i; }",
        "func pos(x) { return x > 0; } if pos(2) and pos(-1) { print 1; } else { print 0; }",
        "func side(x) { print x; return x; } print 0 and side(1); print side(2) or side(3);",
        "func loop(n) { return loop(n + 1); } print loop(0);",
        # compile errors must not be hidden by folding away the code that contains them
        "print 0 and missing();",
        "print 1 or f(1, 2); func f(a) { return a; }",
    ]

    def outcome(self, source, optimize):
        try:
            return ("ok", run_source(source, optimize))
        except MiniLangError as e:
            return (type(e).__name__, e.message, e.line)

    def test_snippets(self):
        for src in self.PROGRAMS:
            with self.subTest(src=src):
                self.assertEqual(self.outcome(src, True), self.outcome(src, False))

    def test_compile_errors_survive_folding(self):
        self.assertEqual(self.outcome("print 0 and missing();", True)[0], "CompileError")

    def test_example_files(self):
        for name in EXAMPLES:
            with self.subTest(name=name):
                with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as f:
                    src = f.read()
                self.assertEqual(self.outcome(src, True), self.outcome(src, False))
                self.assertLess(len(compile_source(src, True)), len(compile_source(src, False)))


if __name__ == "__main__":
    unittest.main()
