import io
import subprocess
import sys
import unittest

from tests.helpers import ROOT, compile_source, run_source
from compiler import Instruction as I
from errors import VMError
from vm import VM, text_tracer


class VMTests(unittest.TestCase):
    def test_raw_bytecode(self):
        out = io.StringIO()
        VM([I("PUSH", 6), I("PUSH", 7), I("MUL"), I("PRINT"), I("HALT")], out=out).run()
        self.assertEqual(out.getvalue(), "42\n")

    def test_arithmetic_and_division_truncates_toward_zero(self):
        self.assertEqual(run_source("print 7 / 2; print -7 / 2; print 2 - 5 * 2;"),
                         ["3", "-3", "-8"])

    def test_comparisons_produce_0_or_1(self):
        self.assertEqual(run_source("print 1 < 2; print 2 <= 1; print 3 == 3; print 3 != 3;"),
                         ["1", "0", "1", "0"])

    def test_logic_short_circuits(self):
        # The right side would divide by zero if it were evaluated.
        self.assertEqual(run_source("print 0 and 1 / 0; print 1 or 1 / 0; print not 5;"),
                         ["0", "1", "0"])

    def test_if_else_and_while(self):
        src = """
        i = 0; total = 0;
        while i < 5 { total = total + i; i = i + 1; }
        if total == 10 { print 1; } else { print 0; }
        """
        self.assertEqual(run_source(src), ["1"])

    def test_else_if_chain(self):
        src = "x = 2; if x == 1 { print 10; } else if x == 2 { print 20; } else { print 30; }"
        self.assertEqual(run_source(src), ["20"])

    def test_recursion(self):
        src = """
        func fact(n) { if n <= 1 { return 1; } return n * fact(n - 1); }
        func fib(n) { if n < 2 { return n; } return fib(n - 1) + fib(n - 2); }
        print fact(10); print fib(15);
        """
        self.assertEqual(run_source(src), ["3628800", "610"])

    def test_mutual_recursion_and_call_before_definition(self):
        src = """
        print is_even(7);
        func is_even(n) { if n == 0 { return 1; } return is_odd(n - 1); }
        func is_odd(n) { if n == 0 { return 0; } return is_even(n - 1); }
        """
        self.assertEqual(run_source(src), ["0"])

    def test_each_call_has_its_own_locals(self):
        # If `n` were shared between calls, the recursive call would clobber it.
        src = "func f(n) { if n > 0 { f(n - 1); } print n; } f(3);"
        self.assertEqual(run_source(src), ["0", "1", "2", "3"])

    def test_locals_do_not_leak_and_globals_are_readable(self):
        src = """
        x = 1; scale = 10;
        func g(y) { x = 99; return y * scale; }
        print g(4); print x;
        """
        self.assertEqual(run_source(src), ["40", "1"])

    def test_local_of_caller_is_not_visible_to_callee(self):
        src = "func inner() { return secret; }\nfunc outer() { secret = 5; return inner(); }\nprint outer();"
        with self.assertRaises(VMError) as cm:
            run_source(src)
        self.assertIn("undefined variable 'secret'", cm.exception.message)
        self.assertEqual(cm.exception.line, 1)

    def test_function_without_return_gives_0(self):
        self.assertEqual(run_source("func f() { x = 1; } print f();"), ["0"])

    def test_return_from_inside_a_loop(self):
        src = "func first_over(n) { for i = 0; ; i = i + 1 { if i * i > n { return i; } } } print first_over(50);"
        self.assertEqual(run_source(src), ["8"])

    def test_call_statement_leaves_stack_empty(self):
        out = io.StringIO()
        vm = VM(compile_source("func f() { return 7; } f(); f();"), out=out)
        vm.run()
        self.assertEqual(vm.stack, [])

    def test_infinite_recursion_hits_call_depth_limit(self):
        with self.assertRaises(VMError) as cm:
            run_source("func f(n) {\n return f(n + 1);\n}\nprint f(0);")
        self.assertIn("maximum call depth", cm.exception.message)
        self.assertEqual(cm.exception.line, 2)

    def test_for_loop_with_break_and_continue(self):
        src = """
        for i = 0; i < 10; i = i + 1 {
            if i == 2 { continue; }
            if i == 5 { break; }
            print i;
        }
        print i;
        """
        self.assertEqual(run_source(src), ["0", "1", "3", "4", "5"])

    def test_break_in_nested_loops_leaves_inner_only(self):
        src = """
        for i = 0; i < 3; i = i + 1 {
            j = 0;
            while 1 { if j == i { break; } j = j + 1; }
            print j;
        }
        """
        self.assertEqual(run_source(src), ["0", "1", "2"])

    def test_undefined_variable_error_has_line(self):
        with self.assertRaises(VMError) as cm:
            run_source("x = 1;\nprint y;")
        self.assertEqual(cm.exception.line, 2)

    def test_division_by_zero(self):
        with self.assertRaises(VMError):
            run_source("print 1 / 0;")

    def test_trace_logs_every_instruction_with_stack(self):
        code = [I("PUSH", 2), I("STORE", "x"), I("LOAD", "x"), I("PUSH", 1),
                I("ADD"), I("PRINT"), I("HALT")]
        out, trace = io.StringIO(), io.StringIO()
        VM(code, out=out, on_step=text_tracer(trace)).run()
        lines = trace.getvalue().splitlines()
        self.assertEqual(len(lines), len(code))
        self.assertTrue(lines[4].startswith("[0004] ADD"))
        self.assertIn("stack=[3]", lines[4])
        self.assertIn("stack=[]", lines[-1])
        self.assertEqual(out.getvalue(), "3\n")  # program output stays separate

    def test_output_limit(self):
        code = [I("PUSH", 1), I("PRINT"), I("JUMP", 0)]
        out = io.StringIO()
        with self.assertRaises(VMError) as cm:
            VM(code, out=out, max_output_lines=3).run()
        self.assertIn("output limit", cm.exception.message)
        self.assertEqual(out.getvalue(), "1\n1\n1\n")

    def test_step_limit(self):
        with self.assertRaises(VMError) as cm:
            VM([I("JUMP", 0)], max_steps=50).run()
        self.assertIn("step limit", cm.exception.message)

    def run_main(self, *args):
        result = subprocess.run([sys.executable, "main.py", *args],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_demo_end_to_end(self):
        expected = ["16", "3", "1", "15", "120", "6", "-1", "4", "-1", "2", "-1"]
        self.assertEqual(self.run_main("examples/demo.ml").split(), expected)
        self.assertEqual(self.run_main("examples/demo.ml", "--no-opt").split(), expected)

    def test_trace_flag(self):
        stdout = self.run_main("examples/demo.ml", "--trace")
        self.assertIn("HALT", stdout.splitlines()[-1])

    def test_functions_example_end_to_end(self):
        expected = ["120", "0", "1", "1", "2", "3", "5", "8", "13", "21", "34",
                    "6", "1", "1", "1", "3", "5", "7", "1", "3", "40"]
        self.assertEqual(self.run_main("examples/functions.ml").split(), expected)
        self.assertEqual(self.run_main("examples/functions.ml", "--no-opt").split(), expected)

    def test_trace_shows_call_depth(self):
        stdout = self.run_main("examples/functions.ml", "--trace")
        self.assertIn("in fact(n) (depth 5)", stdout)


if __name__ == "__main__":
    unittest.main()
