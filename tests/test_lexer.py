import unittest

from tests.helpers import ROOT  # noqa: F401  (sets up sys.path)
from errors import LexError
from lexer import EOF, IDENT, INT, KEYWORD, OP, Token, tokenize


class LexerTests(unittest.TestCase):
    def test_simple_assignment(self):
        self.assertEqual(tokenize("x = 42;"), [
            Token(IDENT, "x", 1), Token(OP, "=", 1), Token(INT, 42, 1),
            Token(OP, ";", 1), Token(EOF, None, 1),
        ])

    def test_keywords_and_two_char_operators(self):
        types = [(t.type, t.value) for t in tokenize("if a <= b and not c != d")]
        self.assertEqual(types, [
            (KEYWORD, "if"), (IDENT, "a"), (OP, "<="), (IDENT, "b"),
            (KEYWORD, "and"), (KEYWORD, "not"), (IDENT, "c"), (OP, "!="),
            (IDENT, "d"), (EOF, None),
        ])

    def test_function_and_loop_keywords_and_comma(self):
        types = [(t.type, t.value) for t in tokenize("func f(a, b) for break continue return")]
        self.assertEqual(types, [
            (KEYWORD, "func"), (IDENT, "f"), (OP, "("), (IDENT, "a"), (OP, ","),
            (IDENT, "b"), (OP, ")"), (KEYWORD, "for"), (KEYWORD, "break"),
            (KEYWORD, "continue"), (KEYWORD, "return"), (EOF, None),
        ])

    def test_line_numbers_and_comments(self):
        tokens = tokenize("a = 1; # comment\n\nprint a;")
        self.assertEqual([t.line for t in tokens], [1, 1, 1, 1, 3, 3, 3, 3])
        self.assertEqual(tokens[-1].type, EOF)

    def test_identifier_containing_keyword(self):
        self.assertEqual(tokenize("iffy")[0], Token(IDENT, "iffy", 1))

    def test_bad_character_reports_line(self):
        with self.assertRaises(LexError) as cm:
            tokenize("x = 1;\ny = 2 @ 3;")
        self.assertEqual(cm.exception.line, 2)


if __name__ == "__main__":
    unittest.main()
