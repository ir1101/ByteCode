"""Semantic analysis: symbol tables, scope errors and warnings."""
import unittest

from tests.helpers import ROOT  # noqa: F401  (sets up sys.path)
from api import run_pipeline
from errors import SemanticError
from lexer import tokenize
from parser import parse
from semantic import analyze, format_symbols


def analysis(source, predefined=()):
    return analyze(parse(tokenize(source)), predefined)


def warnings(source, predefined=()):
    return [(w["line"], w["code"]) for w in analysis(source, predefined).to_dict()["warnings"]]


class ErrorTests(unittest.TestCase):
    def assert_error(self, source, message, line):
        with self.assertRaises(SemanticError) as cm:
            analysis(source)
        self.assertIn(message, cm.exception.message)
        self.assertEqual(cm.exception.line, line)

    def test_undefined_variable_caught_before_running(self):
        self.assert_error("x = 1;\nprint y;", "undefined variable 'y'", 2)

    def test_undefined_variable_inside_function(self):
        self.assert_error("func f() {\n  return z;\n}\nprint f();", "undefined variable 'z' in f()", 2)

    def test_caller_locals_are_not_visible_to_callee(self):
        self.assert_error("func inner() { return secret; }\nfunc outer() { secret = 5; return inner(); }\nprint outer();",
                          "undefined variable 'secret'", 1)

    def test_function_errors(self):
        self.assert_error("print nope(1);", "undefined function 'nope'", 1)
        self.assert_error("func f(a) { return a; }\nprint f(1, 2);", "takes 1 argument(s), but 2 were given", 2)
        self.assert_error("func f() { }\nfunc f() { }", "already defined on line 1", 2)
        self.assert_error("func f(a, a) { }", "duplicate parameter 'a'", 1)
        self.assert_error("func len(a) { return 1; }", "built-in function", 1)
        self.assert_error("print len(1, 2);", "built-in 'len' takes 1 argument", 1)

    def test_placement_errors(self):
        self.assert_error("x = 1;\nreturn x;", "'return' outside a function", 2)
        self.assert_error("if 1 {\n  break;\n}", "'break' outside a loop", 2)
        self.assert_error("continue;", "'continue' outside a loop", 1)
        self.assert_error("func f() {\n  break;\n}\nwhile 1 { f(); }", "'break' outside a loop", 2)

    def test_dead_code_is_still_checked(self):
        # The optimizer would delete this branch, but the error must still be reported.
        self.assert_error("if 0 {\n  print missing;\n}", "undefined variable 'missing'", 2)

    def test_predefined_inputs_are_known(self):
        self.assertEqual(warnings("print n * 2;", predefined=["n"]), [])

    def test_pipeline_reports_semantic_stage(self):
        r = run_pipeline("x = 1;\nprint y;")
        self.assertEqual((r["error"]["stage"], r["error"]["line"]), ("semantic", 2))
        self.assertIsNotNone(r["ast"])
        self.assertIsNone(r["bytecode"])


class WarningTests(unittest.TestCase):
    def test_clean_program_has_no_warnings(self):
        self.assertEqual(warnings("x = 1;\nfunc f(a) { return a + x; }\nprint f(2);"), [])

    def test_maybe_unassigned_after_if_without_else(self):
        self.assertEqual(warnings("if n > 0 { x = 1; }\nprint x;", ["n"]), [(2, "maybe-unassigned")])

    def test_assigned_on_both_branches_is_fine(self):
        self.assertEqual(warnings("if n > 0 { x = 1; } else { x = 2; }\nprint x;", ["n"]), [])

    def test_assigned_only_inside_loop(self):
        self.assertIn((3, "maybe-unassigned"), warnings("i = 0;\nwhile i < 3 { last = i; i = i + 1; }\nprint last;"))

    def test_reported_once_per_variable(self):
        src = "while count > 0 {\n  print count;\n  count = count - 1;\n}"
        self.assertEqual(warnings(src), [(1, "maybe-unassigned")])

    def test_scope_trap(self):
        src = "total = 0;\nfunc add(x) {\n  total = total + x;\n}\nadd(5);\nprint total;"
        result = analysis(src).to_dict()["warnings"]
        self.assertEqual([(w["line"], w["code"]) for w in result], [(3, "scope-trap")])
        self.assertIn("reads the global 'total'", result[0]["message"])

    def test_unreachable_code(self):
        self.assertEqual(warnings("func f() {\n  return 1;\n  print 2;\n}\nprint f();"), [(3, "unreachable")])
        self.assertIn((3, "unreachable"), warnings("while 1 {\n  break;\n  print 1;\n}"))
        both = "func g(n) {\n  if n { return 1; } else { return 2; }\n  print 3;\n}\nprint g(1);"
        self.assertEqual(warnings(both), [(3, "unreachable")])

    def test_unused_symbols(self):
        self.assertEqual(warnings("x = 1;"), [(1, "unused")])
        self.assertEqual(warnings("func f(a) { return 1; }\nprint f(2);"), [(1, "unused")])   # parameter a
        self.assertEqual(warnings("func f() { return 1; }"), [(1, "unused")])                 # never called
        self.assertEqual(warnings("func f() { t = 1; return 2; }\nprint f();"), [(1, "unused")])


class SymbolTableTests(unittest.TestCase):
    SRC = "limit = 3;\nfunc below(x) {\n  y = x;\n  return y < limit;\n}\nprint below(2);\nprint below(9);"

    def test_symbol_table_contents(self):
        table = analysis(self.SRC).to_dict()
        self.assertEqual(table["globals"], [{"name": "limit", "kind": "global", "line": 1,
                                             "assigned": [1], "reads": [4]}])
        (fn,) = table["functions"]
        self.assertEqual((fn["signature"], fn["line"], fn["calls"]), ("below(x)", 2, [6, 7]))
        self.assertEqual({s["name"]: s["kind"] for s in fn["symbols"]}, {"x": "parameter", "y": "local"})
        self.assertEqual(fn["globals_read"], [{"name": "limit", "reads": [4]}])

    def test_text_format(self):
        text = format_symbols(analysis(self.SRC))
        self.assertIn("function below(x)", text)
        self.assertIn("limit", text)

    def test_pipeline_includes_symbols_and_warnings(self):
        r = run_pipeline("x = 1;\nprint 2;")
        self.assertEqual(r["symbols"]["globals"][0]["name"], "x")
        self.assertEqual(r["warnings"][0]["code"], "unused")


class DeadStoreWarningTests(unittest.TestCase):
    def warnings(self, source):
        return [(w["line"], w["code"]) for w in analyze(parse(tokenize(source))).to_dict()["warnings"]]

    def test_overwritten_value(self):
        self.assertEqual(self.warnings("x = 0;\nx = 5;\nprint x;"), [(1, "dead-store")])

    def test_initialised_then_set_on_every_branch(self):
        src = "c = 1;\nx = 0;\nif c { x = 1; } else { x = 2; }\nprint x;"
        self.assertEqual(self.warnings(src), [(2, "dead-store")])

    def test_value_left_at_the_end(self):
        self.assertEqual(self.warnings("x = 1;\nprint x;\nx = 2;"), [(3, "dead-store")])

    def test_never_read_at_all_is_only_unused(self):
        self.assertEqual(self.warnings("x = 1;\nx = 2;"), [(1, "unused")])

    def test_scope_trap_line_keeps_its_own_warning(self):
        src = "total = 0;\nfunc add(x) { total = total + x; }\nadd(1);\nprint total;"
        self.assertEqual(self.warnings(src), [(2, "scope-trap")])

    def test_examples_have_no_warnings(self):
        for name in ("demo.ml", "functions.ml", "optimize.ml", "arrays.ml", "dataflow.ml"):
            with self.subTest(name=name):
                with open(f"{ROOT}/examples/{name}", encoding="utf-8") as f:
                    self.assertEqual(self.warnings(f.read()), [])


if __name__ == "__main__":
    unittest.main()
