"""The type checker: inferred number / list types, and errors only when a type is certain to be wrong."""
import os
import unittest

from tests.helpers import ROOT
from api import lint, run_pipeline
from errors import TypeCheckError
from lexer import tokenize
from levels import LEVELS, LEVELS_BY_ID, check_level
from parser import parse
from typecheck import ANY, LST, NUM, check_types, show


def types_of(source, inputs=()):
    return check_types(parse(tokenize(source)), inputs)


def type_errors(source, inputs=()):
    try:
        types_of(source, inputs)
    except TypeCheckError as e:
        return [(err.line, err.message) for err in e.errors]
    return []


class CertainErrorsTests(unittest.TestCase):
    def test_arithmetic_and_comparison_on_a_list(self):
        self.assertEqual(type_errors("a = [1];\nprint a + 1;"), [(2, "'+' needs two numbers, but 'a' is a list")])
        self.assertIn("'<' needs two numbers", type_errors("a = [1];\nprint 1 < a;")[0][1])
        self.assertIn("'-' needs a number", type_errors("a = [1];\nprint -a;")[0][1])

    def test_a_list_used_as_a_condition(self):
        errors = type_errors("a = [1];\nif a { print 1; }\nwhile not a { }\nprint a or 1;")
        self.assertEqual([line for line, _ in errors], [2, 3, 4])
        self.assertIn("a condition must be a number", errors[0][1])
        self.assertIn("'not' needs a number", errors[1][1])
        self.assertIn("'or' needs numbers", errors[2][1])

    def test_a_number_used_as_a_list(self):
        errors = type_errors("n = 5;\nprint n[0];\nprint len(n);\nappend(n, 1);\nn[0] = 1;")
        self.assertEqual([line for line, _ in errors], [2, 3, 4, 5])
        self.assertIn("'n' is a number, so it can't be indexed", errors[0][1])

    def test_a_list_as_an_index(self):
        self.assertIn("index must be a number", type_errors("a = [1];\nprint a[a];")[0][1])

    def test_unnamed_values_are_described(self):
        self.assertIn("'g[0]' is a number", type_errors("g = [1, 2];\nprint g[0][1];")[0][1])
        self.assertIn("'mk()' is a list", type_errors("func mk() { return [1]; }\nprint mk() * 2;")[0][1])

    def test_every_error_at_once_in_line_order(self):
        errors = type_errors("a = [1];\nn = 1;\nprint n[0];\nprint a + 1;\nprint len(n);")
        self.assertEqual([line for line, _ in errors], [3, 4, 5])

    def test_equality_works_on_any_types(self):
        self.assertEqual(type_errors("a = [1];\nprint a == 1;\nprint a != [1];"), [])


class NoFalseAlarmsTests(unittest.TestCase):
    def test_a_value_that_could_be_either_is_left_to_runtime(self):
        self.assertEqual(type_errors("x = 1;\nif c { x = [1]; }\nprint x + 1;", {"c": 0}), [])

    def test_a_function_nothing_calls_could_get_anything(self):
        self.assertEqual(type_errors("func f(a) { return a + 1; }"), [])

    def test_nested_lists_make_elements_either_type(self):
        self.assertEqual(type_errors("g = [[1], 2];\nprint g[1] + 1;"), [])

    def test_inputs_known_only_by_name_are_either_type(self):
        self.assertEqual(type_errors("print xs[0] + 1;", ["xs"]), [])

    def test_examples_and_level_solutions_type_check(self):
        for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
            with self.subTest(example=name):
                with open(os.path.join(ROOT, "examples", name), encoding="utf-8") as f:
                    self.assertEqual(type_errors(f.read()), [])
        for level in LEVELS:
            for ref in level.references:
                with self.subTest(level=level.id):
                    epilogue = level.tests[0].epilogue
                    self.assertEqual(type_errors(ref + "\n" + epilogue, level.tests[0].inputs), [])


class InferenceTests(unittest.TestCase):
    def test_variable_types(self):
        t = types_of("a = [1, 2];\nn = len(a);\nx = 1;\nif n { x = a; }")
        self.assertEqual((t.globals["a"], t.globals["n"], t.globals["x"]), (LST, NUM, ANY))
        self.assertEqual(t.elements, NUM)

    def test_parameters_and_returns_across_calls(self):
        t = types_of("func first(xs) { return xs[0]; }\nfunc wrap(v) { return [v]; }\nprint first(wrap(3));")
        self.assertEqual(t.signature("first"), "first(xs: list) -> number")
        self.assertEqual(t.signature("wrap"), "wrap(v: number) -> list")

    def test_recursion_reaches_a_fixed_point(self):
        t = types_of("func fact(n) { if n <= 1 { return 1; } return n * fact(n - 1); }\nprint fact(5);")
        self.assertEqual(t.signature("fact"), "fact(n: number) -> number")

    def test_a_global_read_inside_a_function(self):
        self.assertIn("'g' is a list", type_errors("g = [1];\nfunc f() { return g + 1; }\nprint f();")[0][1])

    def test_scope_trap_may_read_the_global(self):
        # total is assigned only when x is true, so the read may fall back to the global list
        src = "total = [1];\nfunc add(x) { if x { total = 5; } return total + x; }\nprint add(1);"
        self.assertEqual(type_errors(src), [])

    def test_input_values_give_types(self):
        t = types_of("print n;", {"n": 3, "xs": [[1]]})
        self.assertEqual((t.globals["n"], t.globals["xs"], t.elements), (NUM, LST, ANY))

    def test_to_dict(self):
        d = types_of("a = [1];\nfunc f(v) { w = v; return w; }\nprint f(a);").to_dict()
        self.assertEqual(d["globals"], {"a": "list"})
        self.assertEqual(d["functions"]["f"]["params"], {"v": "list"})
        self.assertEqual(d["functions"]["f"]["locals"], {"w": "list"})
        self.assertEqual(d["elements"], "number")
        self.assertEqual(show(ANY), "number or list")


class TypeStageTests(unittest.TestCase):
    def test_pipeline_stage(self):
        r = run_pipeline("a = [1];\nprint a + 1;")
        self.assertEqual((r["error"]["stage"], r["error"]["line"]), ("type", 2))
        self.assertIsNotNone(r["symbols"])      # semantic analysis ran before it
        self.assertIsNone(r["bytecode"])        # nothing is compiled after a type error
        ok = run_pipeline("print 1;")
        self.assertEqual(ok["types"]["elements"], "no value")

    def test_lint_reports_type_errors(self):
        r = lint("n = 1;\nprint n[0];")
        self.assertEqual([(e["stage"], e["line"]) for e in r["errors"]], [("type", 2)])

    def test_bug_hunt_starts_with_a_type_error(self):
        level = LEVELS_BY_ID["b8"]
        result = check_level(level, level.starter)
        self.assertFalse(result["passed"])
        self.assertEqual(result["tests"][0]["error"]["stage"], "type")
        self.assertEqual(check_level(level, level.references[0])["star_count"], 3)


if __name__ == "__main__":
    unittest.main()
