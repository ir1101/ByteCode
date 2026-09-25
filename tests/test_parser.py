import unittest

from tests.helpers import ROOT  # noqa: F401  (sets up sys.path)
from ast_nodes import (Assign, BinOp, Block, Break, Call, Continue, ExprStmt,
                       For, FuncDef, If, LogicalOp, Number, Print, Return,
                       UnaryOp, Var, While)
from errors import ParseError
from lexer import tokenize
from parser import parse


def stmts(source):
    return parse(tokenize(source)).statements


class ParserTests(unittest.TestCase):
    def test_precedence_mul_over_add(self):
        (s,) = stmts("x = 1 + 2 * 3;")
        self.assertEqual(s, Assign("x", BinOp("+", Number(1),
                                              BinOp("*", Number(2), Number(3)))))

    def test_left_associative_subtraction(self):
        (s,) = stmts("print 10 - 3 - 2;")
        self.assertEqual(s, Print(BinOp("-", BinOp("-", Number(10), Number(3)), Number(2))))

    def test_logic_precedence(self):
        # not binds tighter than and, which binds tighter than or
        (s,) = stmts("print a or not b and c;")
        self.assertEqual(s, Print(LogicalOp(
            "or", Var("a"),
            LogicalOp("and", UnaryOp("not", Var("b")), Var("c")))))

    def test_if_else_and_while(self):
        (s,) = stmts("while i < 3 { if i == 1 { print i; } else { print 0; } }")
        self.assertIsInstance(s, While)
        self.assertEqual(s.condition, BinOp("<", Var("i"), Number(3)))
        inner = s.body.statements[0]
        self.assertEqual(inner, If(BinOp("==", Var("i"), Number(1)),
                                   Block([Print(Var("i"))]),
                                   Block([Print(Number(0))])))

    def test_nodes_carry_line_numbers(self):
        s = stmts("\n\nx = 1;")[0]
        self.assertEqual(s.line, 3)

    def test_missing_semicolon_reports_line_of_statement(self):
        # The ';' is missing from line 1, even though the parser notices on line 2.
        with self.assertRaises(ParseError) as cm:
            stmts("x = 1\ny = 2;")
        self.assertEqual(cm.exception.line, 1)

    def test_other_errors_report_current_token_line(self):
        with self.assertRaises(ParseError) as cm:
            stmts("x = 1;\ny = ;")
        self.assertEqual(cm.exception.line, 2)

    def test_unclosed_block(self):
        with self.assertRaises(ParseError):
            stmts("if 1 { print 1;")

    def test_chained_comparison_rejected(self):
        with self.assertRaises(ParseError):
            stmts("print 1 < 2 < 3;")

    def test_function_definition_and_return(self):
        (f,) = stmts("func add(a, b) { return a + b; }")
        self.assertEqual(f, FuncDef("add", ["a", "b"], Block([
            Return(BinOp("+", Var("a"), Var("b")))])))

    def test_function_without_params_and_bare_return(self):
        (f,) = stmts("func f() { return; }")
        self.assertEqual(f, FuncDef("f", [], Block([Return(None)])))

    def test_call_in_expression_and_as_statement(self):
        s1, s2 = stmts("print 1 + f(2, g(x));\nshow();")
        self.assertEqual(s1, Print(BinOp("+", Number(1),
                                         Call("f", [Number(2), Call("g", [Var("x")])]))))
        self.assertEqual(s2, ExprStmt(Call("show", [])))

    def test_variable_is_not_a_call(self):
        (s,) = stmts("print f + 1;")
        self.assertEqual(s, Print(BinOp("+", Var("f"), Number(1))))

    def test_for_loop_with_all_parts(self):
        (s,) = stmts("for i = 0; i < 3; i = i + 1 { print i; }")
        self.assertEqual(s, For(Assign("i", Number(0)), BinOp("<", Var("i"), Number(3)),
                                Assign("i", BinOp("+", Var("i"), Number(1))),
                                Block([Print(Var("i"))])))

    def test_for_loop_parts_are_optional(self):
        (s,) = stmts("for ;; { break; }")
        self.assertEqual(s, For(None, None, None, Block([Break()])))

    def test_break_and_continue(self):
        (s,) = stmts("while 1 { continue; break; }")
        self.assertEqual(s.body.statements, [Continue(), Break()])

    def test_function_inside_block_rejected(self):
        with self.assertRaises(ParseError) as cm:
            stmts("if 1 {\n func f() { }\n}")
        self.assertEqual(cm.exception.line, 2)

    def test_missing_paren_in_call(self):
        with self.assertRaises(ParseError):
            stmts("print f(1, 2;")


if __name__ == "__main__":
    unittest.main()
