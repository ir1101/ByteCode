import os
import unittest

from tests.helpers import ROOT, compile_source, run_source
from ast_nodes import Assign, BinOp, LogicalOp, Number, Print, Var
from compiler import Instruction as I
from errors import MiniLangError, VMError
from lexer import tokenize
from optimizer import JUMPS, fold_constants, peephole
from parser import parse

EXAMPLES = ("demo.ml", "optimize.ml", "functions.ml", "arrays.ml")


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
        "func loop(n) { return 1 + loop(n + 1); } print loop(0);",
        # constant propagation: joins, loops, functions, possibly-undefined variables
        "x = 3;\ny = x * x;\nif y > 5 { z = y - x; } else { z = 0; }\nprint z; print x + y + z;",
        "i = 0; total = 0; while i < 5 { total = total + i; i = i + 1; } print total; print i;",
        "k = 2; for j = 0; j < 3; j = j + 1 { k = k * 2; } print k;",
        "c = 1; if c { a = 1; } else { a = 2; } print a; c = 0; if c { b = 1; } else { b = 2; } print b;",
        "n = 0;\nif n { x = 5; }\nprint x;",
        "g = 4; func f(a) { b = 3; return a * b + g; } print f(2); g = 10; print f(2);",
        "func h() { v = 2; v = v + 1; return v * v; } print h();",
        "x = 5; x = x + 1; print x; x = x * 2; print x;",
        "d = 0; print 10 / d;",
        # % and arrays
        "print 17 % 5; print -17 % 5; x = 9; print x % 4 + 10 % 3;",
        "a = [1, 2 * 3, 7 % 4]; a[0] = a[1] + a[2]; append(a, len(a)); print a;",
        "a = [];\nfor i = 0; i < 5; i = i + 1 { if i % 2 == 0 { append(a, i); } } print a;",
        "a = [1];\nprint a[3];",
        "print 4 % (2 - 2);",
        # compile errors must not be hidden by folding away the code that contains them
        "print 0 and missing();",
        "print 1 or f(1, 2); func f(a) { return a; }",
        # dead-store elimination must keep anything that can fail or has side effects
        "x = 5; x = 6; print x;",
        "a = [1]; b = a; b[0] = 5; print a;",
        "x = [1]; y = x; print 2;",
        "n = 0;\nif n { y = 1; }\nx = y;\nprint 1;",
        "a = [1, 2];\nx = a + 1;\nprint 0;",
        "d = 0;\nx = 7 / d;\nprint 0;",
        "a = [];\nx = a[0];\nprint 0;",
        "func f() { print 7; return 1; } x = f(); print 0;",
        "func f(c) { if c { v = 1; } w = v; return 0; } print f(1); print f(0);",
        "v = 9; func f(c) { if c { v = 1; } w = v; return w; } print f(1); print f(0);",
        "g = 1; func f() { return g; } g = 2; print f();",
        "i = 0; while i < 3 { x = i; i = i + 1; } print i;",
        "t1 = 100;\ny = 2 * 3 + t1;\nprint y;",
        "x = 1; print x == [1]; y = [x] == [1]; print 3;",
        # tail calls that finish well within the limits behave exactly the same
        "func gcd(a, b) { if b == 0 { return a; } return gcd(b, a % b); } print gcd(1071, 462);",
        "func even(n) { if n == 0 { return 1; } return odd(n - 1); } "
        "func odd(n) { if n == 0 { return 0; } return even(n - 1); } print even(10); print odd(7);",
        "func f(n) { if n > 0 { return f(n - 1); } return 1 / n; } print f(3);",
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
                self.assertLessEqual(len(compile_source(src, True)), len(compile_source(src, False)))


class DeadStoreTests(unittest.TestCase):
    def test_propagation_leaves_only_the_print(self):
        code = compile_source("x = 10;\ny = x * 2;\nprint y;", optimize=True)
        self.assertEqual(code, [I("PUSH", 20), I("PRINT"), I("HALT")])

    def test_overwritten_initial_value_is_removed(self):
        code = compile_source("x = [1, 2];\nx = [3];\nprint x;", optimize=True)
        self.assertEqual([ins.op for ins in code].count("BUILD_LIST"), 1)

    def test_chains_of_dead_copies_are_removed(self):
        code = compile_source("a = [1];\nb = a;\nc = b;\nprint 0;", optimize=True)
        self.assertEqual(code, [I("PUSH", 0), I("PRINT"), I("HALT")])

    def test_stores_that_can_fail_are_kept(self):
        for src in ("x = n / 2;\nprint 0;", "x = a[0];\nprint 0;", "x = f();\nprint 0;\nfunc f() { return 1; }"):
            with self.subTest(src=src):
                self.assertIn("STORE", [ins.op for ins in compile_source(src, optimize=True)])

    def test_dead_stores_in_loops_and_functions(self):
        code = compile_source("func f() { tmp = 5; return 1; }\nprint f();", optimize=True)
        self.assertNotIn("STORE", [ins.op for ins in code])


class TailCallTests(unittest.TestCase):
    SUM = "func sum(n, acc) { if n == 0 { return acc; } return sum(n - 1, acc + n); }\nprint sum(5000, 0);"

    def test_return_of_a_call_becomes_tail_call(self):
        code = compile_source("func f(n) { if n == 0 { return 0; } return f(n - 1); }\nprint f(3);", optimize=True)
        ops = [ins.op for ins in code]
        self.assertIn("TAIL_CALL", ops)
        self.assertEqual(ops.count("CALL"), 1)   # the first call, from top-level code

    def test_a_call_whose_result_is_used_is_not_a_tail_call(self):
        code = compile_source("func f(n) { if n == 0 { return 1; } return n * f(n - 1); }\nprint f(3);", optimize=True)
        self.assertNotIn("TAIL_CALL", [ins.op for ins in code])

    def test_deep_tail_recursion_only_works_optimized(self):
        self.assertEqual(run_source(self.SUM, optimize=True), ["12502500"])
        with self.assertRaises(VMError) as ctx:
            run_source(self.SUM, optimize=False)
        self.assertIn("maximum call depth", ctx.exception.message)

    def test_dataflow_example(self):
        with open(os.path.join(ROOT, "examples", "dataflow.ml"), encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(run_source(src, optimize=True), ["42", "55", "12502500", "21"])
        with self.assertRaises(VMError):   # 5000 nested calls without tail calls
            run_source(src, optimize=False)

    def test_tail_call_keeps_the_callers_place(self):
        src = "func g(x) { return x * 10; }\nfunc f(x) { return g(x + 1); }\nprint 1 + f(2) + 100;"
        self.assertEqual(run_source(src, optimize=True), ["131"])


if __name__ == "__main__":
    unittest.main()
