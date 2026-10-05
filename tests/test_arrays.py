"""The % operator and arrays, through every stage of the pipeline."""
import json
import unittest

from tests.helpers import ROOT, compile_source, run_source  # noqa: F401
from api import run_pipeline
from ast_nodes import ArrayLit, BinOp, Index, IndexAssign, Number, Print, Var
from compiler import Instruction as I
from errors import CompileError, ParseError, VMError
from levels import LEVELS_BY_ID, check_level
from lexer import OP, tokenize
from parser import parse


def stmts(source):
    return parse(tokenize(source)).statements


class LexAndParseTests(unittest.TestCase):
    def test_new_tokens(self):
        ops = [t.value for t in tokenize("a[1] % 2") if t.type == OP]
        self.assertEqual(ops, ["[", "]", "%"])

    def test_modulo_binds_like_multiplication(self):
        (s,) = stmts("print 1 + 7 % 4 * 2;")
        self.assertEqual(s, Print(BinOp("+", Number(1), BinOp("*", BinOp("%", Number(7), Number(4)), Number(2)))))

    def test_array_literal_and_index(self):
        (s,) = stmts("print [1, x][0];")
        self.assertEqual(s, Print(Index(ArrayLit([Number(1), Var("x")]), Number(0))))

    def test_empty_list(self):
        self.assertEqual(stmts("print [];")[0], Print(ArrayLit([])))

    def test_nested_index_assignment(self):
        (s,) = stmts("m[i][j] = 5;")
        self.assertEqual(s, IndexAssign(Index(Var("m"), Var("i")), Var("j"), Number(5)))

    def test_unclosed_list(self):
        with self.assertRaises(ParseError):
            stmts("print [1, 2;")


class CompileTests(unittest.TestCase):
    def test_list_instructions(self):
        self.assertEqual(compile_source("a = [1, 2];\na[0] = a[1];"), [
            I("PUSH", 1), I("PUSH", 2), I("BUILD_LIST", 2), I("STORE", "a"),
            I("LOAD", "a"), I("PUSH", 0),                       # target, index
            I("LOAD", "a"), I("PUSH", 1), I("INDEX"),           # value
            I("STORE_INDEX"), I("HALT"),
        ])

    def test_builtins_compile_to_single_instructions(self):
        code = compile_source("a = [];\nappend(a, 7);\nprint len(a);")
        self.assertIn(I("APPEND"), code)
        self.assertIn(I("LEN"), code)
        self.assertNotIn("CALL", [ins.op for ins in code])

    def test_builtin_argument_count(self):
        with self.assertRaises(CompileError) as cm:
            compile_source("print len();")
        self.assertIn("takes 1 argument", cm.exception.message)

    def test_builtins_cannot_be_redefined(self):
        with self.assertRaises(CompileError):
            compile_source("func append(a, b) { return 0; }")


class RunTests(unittest.TestCase):
    def test_modulo_follows_truncating_division(self):
        self.assertEqual(run_source("print 17 % 5; print -7 % 3; print 7 % -3; print 0 % 4;"),
                         ["2", "-1", "1", "0"])
        # (a / b) * b + a % b == a for every sign combination
        self.assertEqual(run_source("for a = -7; a <= 7; a = a + 7 { for b = -3; b <= 3; b = b + 6 {"
                                    " print (a / b) * b + a % b == a; } }"), ["1"] * 6)

    def test_lists(self):
        src = "a = [3, 1, 2];\na[1] = 10;\nappend(a, 4);\nprint a; print len(a); print a[3]; print [[1], []];"
        self.assertEqual(run_source(src), ["[3, 10, 2, 4]", "4", "4", "[[1], []]"])

    def test_lists_are_shared_by_reference(self):
        src = "func fill(xs) { append(xs, 9); }\na = [];\nb = a;\nfill(b);\nprint a; print a == [9]; print a != [9];"
        self.assertEqual(run_source(src), ["[9]", "1", "0"])

    def test_runtime_errors(self):
        cases = {
            "a = [1];\nprint a[1];": "index 1 is out of range for a list of length 1",
            "a = [1];\nprint a[-1];": "index -1 is out of range",
            "a = [1];\nprint a[[0]];": "a list index must be a number",
            "x = 5;\nprint x[0];": "must be a list, not a number",
            "a = [1];\nprint a * 2;": "'*' needs two numbers, not a list and a number",
            "a = [1];\nif a { print 1; }": "a condition must be a number, not a list",
            "a = [1];\nprint -a;": "must be a number, not a list",
            "print len(5);": "the argument of len() must be a list",
            "print 5 % 0;": "modulo by zero",
        }
        for source, message in cases.items():
            with self.subTest(source=source):
                with self.assertRaises(VMError) as cm:
                    run_source(source)
                self.assertIn(message, cm.exception.message)

    def test_optimizer_folds_modulo_but_not_modulo_by_zero(self):
        self.assertIn(I("PUSH", 2), compile_source("print 17 % 5;", optimize=True))
        with self.assertRaises(VMError):
            run_source("print 1 % 0;", optimize=True)


class ApiTests(unittest.TestCase):
    def test_trace_keeps_old_list_values(self):
        r = run_pipeline("a = [1];\na[0] = 2;\na[0] = 3;", trace=True, optimize=False)
        seen = [s["variables"]["a"] for s in r["trace"] if "a" in s["variables"]]
        self.assertEqual(seen[0], [1])   # later writes must not rewrite earlier snapshots
        self.assertEqual(seen[-1], [3])

    def test_list_containing_itself_is_json_safe(self):
        r = run_pipeline("a = [1];\nappend(a, a);\nprint a;", trace=True)
        self.assertEqual(r["output"], ["[1, [...]]"])
        json.dumps(r)

    def test_inputs_are_not_mutated(self):
        data = {"xs": [3, 1]}
        run_pipeline("xs[0] = 99;", inputs=data)
        self.assertEqual(data, {"xs": [3, 1]})


class LevelTests(unittest.TestCase):
    def test_sorting_level_is_repeatable(self):
        # The check sorts each test's list; doing it twice must give the same result.
        lv = LEVELS_BY_ID["c12"]
        first, second = check_level(lv, lv.references[0]), check_level(lv, lv.references[0])
        self.assertEqual(first["stars"], [True, True, True])
        self.assertEqual(first, second)

    def test_bubble_sort_is_correct_but_misses_size_and_speed(self):
        bubble = ("n = len(xs);\nfor i = 0; i < n; i = i + 1 {\n  for j = 0; j < n - 1 - i; j = j + 1 {\n"
                  "    if xs[j] > xs[j + 1] { t = xs[j]; xs[j] = xs[j + 1]; xs[j + 1] = t; }\n  }\n}\nprint xs;\n")
        self.assertEqual(check_level(LEVELS_BY_ID["c12"], bubble)["stars"], [True, False, False])


if __name__ == "__main__":
    unittest.main()
