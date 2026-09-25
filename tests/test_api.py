import json
import unittest

from tests.helpers import ROOT  # noqa: F401  (sets up sys.path)
from api import MAX_SOURCE_CHARS, run_pipeline


class RunPipelineTests(unittest.TestCase):
    def test_success_returns_every_stage(self):
        r = run_pipeline("x = 2 + 3;\nprint x;")
        self.assertTrue(r["ok"])
        self.assertIsNone(r["error"])
        self.assertEqual(r["tokens"][0], {"type": "IDENT", "value": "x", "line": 1})
        self.assertEqual(r["tokens"][-1]["type"], "EOF")
        self.assertEqual(r["ast"]["type"], "Program")
        self.assertEqual(r["ast"]["statements"][0]["value"]["type"], "BinOp")  # AST is unfolded
        self.assertEqual(r["bytecode"][0],
                         {"addr": 0, "op": "PUSH", "arg": 5, "line": 1, "label": None})
        self.assertEqual(r["optimizer"], {"enabled": True, "before": 7, "after": 5})
        self.assertEqual(r["output"], ["5"])
        self.assertIsNone(r["trace"])

    def test_result_is_json_serialisable(self):
        json.dumps(run_pipeline("print 1;", trace=True))

    def test_optimizer_off(self):
        r = run_pipeline("print 2 * 3;", optimize=False)
        self.assertEqual(r["bytecode"], r["bytecode_unoptimized"])
        self.assertEqual(r["optimizer"]["enabled"], False)

    def test_lex_error_stops_before_tokens(self):
        r = run_pipeline("x = 1;\ny = @;")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], {"stage": "lex", "message": "unexpected character '@'", "line": 2})
        self.assertIsNone(r["tokens"])

    def test_parse_error_keeps_tokens(self):
        r = run_pipeline("x = 1\nprint x;")
        self.assertEqual(r["error"]["stage"], "parse")
        self.assertEqual(r["error"]["line"], 1)
        self.assertIsNotNone(r["tokens"])
        self.assertIsNone(r["ast"])

    def test_runtime_error_keeps_output_so_far(self):
        r = run_pipeline("print 1;\nprint 2;\nprint 3 / 0;")
        self.assertEqual(r["error"], {"stage": "runtime", "message": "division by zero", "line": 3})
        self.assertEqual(r["output"], ["1", "2"])
        self.assertIsNotNone(r["bytecode"])

    def test_trace_snapshots_vm_state(self):
        r = run_pipeline("x = 4;\nprint x * 2;", optimize=False, trace=True)
        steps = r["trace"]
        self.assertEqual([s["op"] for s in steps],
                         ["PUSH", "STORE", "LOAD", "PUSH", "MUL", "PRINT", "HALT"])
        self.assertEqual(steps[1]["variables"], {"x": 4})
        self.assertEqual(steps[4]["stack"], [8])
        self.assertEqual(steps[4]["lines_printed"], 0)
        self.assertEqual(steps[5]["lines_printed"], 1)
        self.assertFalse(r["trace_truncated"])

    def test_trace_shows_call_stack_and_locals(self):
        r = run_pipeline("g = 1;\nfunc f(n) { if n > 0 { return f(n - 1); } return n; }\nprint f(2);",
                         trace=True)
        depth3 = [s for s in r["trace"] if len(s["call_stack"]) == 3]
        self.assertEqual(depth3[0]["op"], "CALL")
        self.assertEqual(depth3[0]["locals"], {})       # frame created, argument not stored yet
        self.assertEqual(depth3[1]["op"], "STORE")
        self.assertEqual(depth3[1]["locals"], {"n": 0})
        self.assertEqual(depth3[1]["call_stack"], ["f(n)", "f(n)", "f(n)"])
        self.assertEqual(depth3[1]["variables"], {"g": 1})
        self.assertIsNone(r["trace"][0]["locals"])  # top-level code has no locals
        self.assertEqual(r["output"], ["0"])

    def test_function_label_in_bytecode(self):
        r = run_pipeline("func f(a) { return a; }\nprint f(1);")
        labels = [ins["label"] for ins in r["bytecode"] if ins["label"]]
        self.assertEqual(labels, ["f(a)"])

    def test_compile_error_keeps_ast(self):
        r = run_pipeline("print f();")
        self.assertEqual(r["error"], {"stage": "compile", "message": "undefined function 'f'", "line": 1})
        self.assertIsNotNone(r["ast"])
        self.assertIsNone(r["bytecode"])

    def test_recursion_depth_limit(self):
        r = run_pipeline("func f() { return f(); } print f();", max_call_depth=50)
        self.assertIn("maximum call depth of 50", r["error"]["message"])

    def test_trace_is_capped(self):
        r = run_pipeline("i = 0; while i < 100 { i = i + 1; }", trace=True, max_trace_steps=10)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["trace"]), 10)
        self.assertTrue(r["trace_truncated"])

    def test_infinite_loop_hits_step_limit(self):
        r = run_pipeline("while 1 { x = 1; }", max_steps=1000)
        self.assertEqual(r["error"]["stage"], "runtime")
        self.assertIn("step limit", r["error"]["message"])

    def test_output_limit(self):
        r = run_pipeline("while 1 { print 1; }", max_output_lines=5)
        self.assertIn("output limit", r["error"]["message"])
        self.assertEqual(len(r["output"]), 5)

    def test_source_too_long(self):
        r = run_pipeline("#" * (MAX_SOURCE_CHARS + 1))
        self.assertEqual(r["error"]["stage"], "input")

    def test_readable_ast_dump(self):
        r = run_pipeline("x = 1;")
        self.assertTrue(r["ast_dump"].startswith("Program  [line 1]"))
        self.assertIn("Assign(name='x')  [line 1]", r["ast_dump"])

    def test_trace_includes_every_frame(self):
        r = run_pipeline("func f(n) { if n > 0 { return f(n - 1); } return n; }\nprint f(1);", trace=True)
        deepest = [s for s in r["trace"] if len(s["frames"]) == 2 and s["op"] == "STORE"][0]
        self.assertEqual(deepest["frames"], [{"name": "f(n)", "locals": {"n": 1}},
                                             {"name": "f(n)", "locals": {"n": 0}}])

    def test_deep_nesting_is_reported_not_crashed(self):
        r = run_pipeline("print " + "(" * 2000 + "1" + ")" * 2000 + ";")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["stage"], "parse")
        self.assertIn("nested too deeply", r["error"]["message"])
        self.assertIsNotNone(r["tokens"])



if __name__ == "__main__":
    unittest.main()
