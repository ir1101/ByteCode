"""The input statement: lexing, parsing, every stage after it, and where the values come from."""
import io
import os
import subprocess
import sys
import unittest

from tests.helpers import ROOT, compile_source
from api import run_pipeline
from errors import ParseError, VMError
from lexer import tokenize
from levels import LEVELS_BY_ID, check_level
from parser import parse
from semantic import analyze
from vm import VM, InputReader


def run(source, stdin, optimize=True):
    out = io.StringIO()
    vm = VM(compile_source(source, optimize), out=out, input=InputReader.from_text(stdin))
    vm.run()
    return out.getvalue().splitlines(), vm.input.used


class InputStatementTests(unittest.TestCase):
    def test_reads_whole_numbers_across_spaces_and_lines(self):
        self.assertEqual(run("input a;\ninput b;\ninput c;\nprint a + b + c;", "1 2\n\n  3\n"), (["6"], 3))

    def test_negative_and_plus_signs(self):
        self.assertEqual(run("input a;\ninput b;\nprint a * b;", "-4 +5"), (["-20"], 2))

    def test_leftover_values_are_not_read(self):
        self.assertEqual(run("input a;\nprint a;", "7 8 9"), (["7"], 1))

    def test_running_out_is_a_runtime_error_with_its_line(self):
        with self.assertRaises(VMError) as ctx:
            run("input a;\ninput b;", "1")
        self.assertEqual(ctx.exception.line, 2)
        self.assertIn("none left", ctx.exception.message)

    def test_a_value_that_is_not_a_whole_number(self):
        for bad in ("abc", "1.5", "²"):
            with self.subTest(bad=bad):
                with self.assertRaises(VMError) as ctx:
                    run("input a;", bad)
                self.assertIn("not a whole number", ctx.exception.message)

    def test_input_inside_a_function_makes_a_local(self):
        src = "func twice() { input v; return v * 2; }\nv = 100;\nprint twice();\nprint v;"
        self.assertEqual(run(src, "21")[0], ["42", "100"])

    def test_loop_until_zero(self):
        src = "total = 0;\ninput x;\nwhile x != 0 { total += x; input x; }\nprint total;"
        self.assertEqual(run(src, "3 4 5 0")[0], ["12"])

    def test_the_optimizer_never_drops_an_input(self):
        # x is never read, but reading it still consumes a value from the input
        src = "input x;\ninput y;\nprint y;"
        self.assertEqual(run(src, "1 2", optimize=True), run(src, "1 2", optimize=False))
        self.assertEqual(sum(ins.op == "INPUT" for ins in compile_source(src, optimize=True)), 2)


class InputFrontEndTests(unittest.TestCase):
    def test_keyword_and_statement(self):
        self.assertEqual(tokenize("input x;")[0].type, "KEYWORD")
        self.assertEqual(type(parse(tokenize("input x;")).statements[0]).__name__, "Input")

    def test_needs_a_variable_name(self):
        with self.assertRaises(ParseError) as ctx:
            parse(tokenize("input 5;"))
        self.assertIn("variable name after 'input'", ctx.exception.message)

    def test_misspelled_keyword_hint(self):
        with self.assertRaises(ParseError) as ctx:
            parse(tokenize("inptu x;"))
        self.assertIn("did you mean 'input'", ctx.exception.message)

    def test_input_counts_as_an_assignment(self):
        analysis = analyze(parse(tokenize("input x;\nprint x;")))
        self.assertEqual(analysis.to_dict()["warnings"], [])
        self.assertEqual(analysis.globals["x"].assigned, [1])


class InputPipelineTests(unittest.TestCase):
    def test_pipeline_reports_values_and_how_many_were_read(self):
        r = run_pipeline("input a;\nprint a;", stdin="5 6", trace=True)
        self.assertEqual(r["output"], ["5"])
        self.assertEqual(r["input"], {"values": ["5", "6"], "used": 1})
        self.assertEqual([s["input_used"] for s in r["trace"]][:2], [1, 1])   # INPUT, then STORE

    def test_ir_shows_the_read(self):
        r = run_pipeline("input a;\nprint a;", stdin="1")
        self.assertEqual(r["ir"]["procedures"][0]["blocks"][0]["lines"][0], "a = input")

    def test_input_too_long(self):
        r = run_pipeline("input a;", stdin="1 " * 60_000)
        self.assertEqual(r["error"]["stage"], "input")

    def test_running_total_level(self):
        level = LEVELS_BY_ID["c13"]
        self.assertTrue(check_level(level, level.references[0])["passed"])
        self.assertFalse(check_level(level, "print 12;")["passed"])   # hard-coding fails on other inputs

    def test_command_line_input_flag(self):
        path = os.path.join(ROOT, "tests", "_input_test.ml")
        with open(path, "w", encoding="utf-8") as f:
            f.write("input a;\ninput b;\nprint a * b;\n")
        try:
            done = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), path, "--input", "6 7"],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(done.stdout.strip(), "42")
            piped = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), path],
                                   input="3\n5\n", capture_output=True, text=True, timeout=30)
            self.assertEqual(piped.stdout.strip(), "15")
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
