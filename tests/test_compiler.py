import unittest

from tests.helpers import ROOT  # noqa: F401  (sets up sys.path)
from compiler import Instruction as I, compile_program
from errors import CompileError
from lexer import tokenize
from parser import parse


def compile_src(source):
    return compile_program(parse(tokenize(source)))


class CompilerTests(unittest.TestCase):
    def test_assignment_and_arithmetic(self):
        self.assertEqual(compile_src("x = 1 + 2 * 3;"), [
            I("PUSH", 1), I("PUSH", 2), I("PUSH", 3), I("MUL"), I("ADD"),
            I("STORE", "x"), I("HALT"),
        ])

    def test_print_variable(self):
        self.assertEqual(compile_src("print x;"), [I("LOAD", "x"), I("PRINT"), I("HALT")])

    def test_if_else_jump_targets(self):
        self.assertEqual(compile_src("if 1 { print 2; } else { print 3; }"), [
            I("PUSH", 1),               # 0
            I("JUMP_IF_FALSE", 5),      # 1 -> else branch
            I("PUSH", 2), I("PRINT"),   # 2, 3
            I("JUMP", 7),               # 4 -> end
            I("PUSH", 3), I("PRINT"),   # 5, 6
            I("HALT"),                  # 7
        ])

    def test_while_jumps_back_to_condition(self):
        self.assertEqual(compile_src("while x { x = x - 1; }"), [
            I("LOAD", "x"),             # 0
            I("JUMP_IF_FALSE", 7),      # 1 -> exit
            I("LOAD", "x"), I("PUSH", 1), I("SUB"), I("STORE", "x"),  # 2-5
            I("JUMP", 0),               # 6 -> condition
            I("HALT"),                  # 7
        ])

    def test_instructions_keep_source_lines(self):
        code = compile_src("x = 1;\nprint x;")
        self.assertEqual([ins.line for ins in code[:-1]], [1, 1, 2, 2])

    def test_function_layout_and_call(self):
        code = compile_src("print sub(5, 2);\nfunc sub(a, b) { return a - b; }")
        self.assertEqual(code, [
            I("PUSH", 5), I("PUSH", 2),      # 0, 1: arguments, left to right
            I("CALL", 5),                    # 2 -> function entry
            I("PRINT"), I("HALT"),           # 3, 4
            I("STORE", "b"), I("STORE", "a"),  # 5, 6: last argument is on top
            I("LOAD", "a"), I("LOAD", "b"), I("SUB"), I("RET"),  # 7-10
            I("PUSH", 0), I("RET"),          # 11, 12: implicit "return 0"
        ])
        self.assertEqual(code[5].label, "sub(a, b)")

    def test_call_statement_discards_result(self):
        code = compile_src("f();\nfunc f() { }")
        self.assertEqual(code[:3], [I("CALL", 3), I("POP"), I("HALT")])

    def test_for_loop_continue_runs_update_and_break_exits(self):
        self.assertEqual(compile_src("for i = 0; i < 3; i = i + 1 { continue; break; }"), [
            I("PUSH", 0), I("STORE", "i"),                  # 0, 1: init
            I("LOAD", "i"), I("PUSH", 3), I("LT"),          # 2-4: condition
            I("JUMP_IF_FALSE", 13),                         # 5 -> end
            I("JUMP", 8),                                   # 6: continue -> update
            I("JUMP", 13),                                  # 7: break -> end
            I("LOAD", "i"), I("PUSH", 1), I("ADD"), I("STORE", "i"),  # 8-11: update
            I("JUMP", 2),                                   # 12 -> condition
            I("HALT"),                                      # 13
        ])

    def test_while_continue_goes_to_condition(self):
        code = compile_src("while x { continue; }")
        self.assertEqual(code[2], I("JUMP", 0))

    def test_break_only_leaves_innermost_loop(self):
        code = compile_src("while a { while b { break; } print 1; }")
        # inner loop: 2 LOAD b; 3 JIF 6; 4 JUMP(break) 6; 5 JUMP 2; 6 PUSH 1
        self.assertEqual(code[4], I("JUMP", 6))
        self.assertEqual(code[6], I("PUSH", 1))


class SemanticErrorTests(unittest.TestCase):
    def assert_compile_error(self, source, message, line):
        with self.assertRaises(CompileError) as cm:
            compile_src(source)
        self.assertIn(message, cm.exception.message)
        self.assertEqual(cm.exception.line, line)

    def test_undefined_function(self):
        self.assert_compile_error("x = 1;\nprint nope(1);", "undefined function 'nope'", 2)

    def test_wrong_argument_count(self):
        self.assert_compile_error("func f(a) { return a; }\nprint f(1, 2);",
                                  "takes 1 argument(s), but 2 were given", 2)

    def test_duplicate_function(self):
        self.assert_compile_error("func f() { }\nfunc f() { }", "already defined on line 1", 2)

    def test_duplicate_parameter(self):
        self.assert_compile_error("func f(a, a) { }", "duplicate parameter 'a'", 1)

    def test_return_outside_function(self):
        self.assert_compile_error("x = 1;\nreturn x;", "'return' outside a function", 2)

    def test_break_outside_loop(self):
        self.assert_compile_error("if 1 {\n break;\n}", "'break' outside a loop", 2)

    def test_continue_outside_loop(self):
        self.assert_compile_error("continue;", "'continue' outside a loop", 1)

    def test_loop_does_not_reach_into_function(self):
        # The break is in a function called from a loop, not in the loop itself.
        self.assert_compile_error("func f() {\n break;\n}\nwhile 1 { f(); }",
                                  "'break' outside a loop", 2)


if __name__ == "__main__":
    unittest.main()
