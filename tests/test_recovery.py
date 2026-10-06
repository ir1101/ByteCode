"""Error recovery and hints: every lexer, parser and semantic error in one run."""
import unittest

from tests.helpers import ROOT, run_source  # noqa: F401
from api import lint
from errors import LexError, ParseError, SemanticError
from lexer import tokenize
from parser import parse
from semantic import analyze


def errors_of(source):
    """[(line, message)] for every error of the first failing stage."""
    try:
        analyze(parse(tokenize(source)))
    except (LexError, ParseError, SemanticError) as e:
        return [(err.line, err.message) for err in e.errors]
    return []


class LexerRecoveryTests(unittest.TestCase):
    def test_every_bad_character_is_reported(self):
        errs = errors_of("x = 1 @ 2;\ny = 3;\nz = $;")
        self.assertEqual([line for line, _ in errs], [1, 3])

    def test_a_run_of_bad_characters_is_one_error_with_a_hint(self):
        ((line, message),) = errors_of("if a && b { print 1; }")
        self.assertEqual(line, 1)
        self.assertIn("'&&'", message)
        self.assertIn("'and'", message)

    def test_hints_for_other_languages(self):
        self.assertIn("'or'", errors_of("print a || b;")[0][1])
        self.assertIn("strings", errors_of('print "hi";')[0][1])
        self.assertIn("not x", errors_of("print !a;")[0][1])

    def test_bad_number_literal_is_skipped_whole(self):
        errs = errors_of("x = 12ab;\ny = 3cd;")
        self.assertEqual([line for line, _ in errs], [1, 2])
        self.assertIn("'12ab'", errs[0][1])


class ParserRecoveryTests(unittest.TestCase):
    def test_missing_semicolons_on_every_line(self):
        errs = errors_of("x = 1\ny = 2\nprint x + y")
        self.assertEqual([line for line, _ in errs], [1, 2, 3])
        self.assertTrue(all("expected ';'" in m for _, m in errs))

    def test_panic_mode_skips_to_the_next_statement(self):
        errs = errors_of("x = 1 +;\nprint x;\ny = (2;\nprint y;")
        self.assertEqual([line for line, _ in errs], [1, 3])

    def test_one_error_per_line(self):
        self.assertEqual(len(errors_of("x = = = ;")), 1)

    def test_errors_inside_blocks_and_functions(self):
        src = "func f(n) {\n    if n > {\n        return 1;\n    }\n    retrun 2;\n}\nprint f(1)"
        self.assertEqual([line for line, _ in errors_of(src)], [2, 5, 7])

    def test_stray_and_missing_braces(self):
        self.assertEqual(errors_of("x = 1;\n}\nprint x;"), [(2, "expected a statement, found '}'")])
        self.assertEqual(errors_of("while 1 {\n    print 1;\n"), [(1, "unclosed '{' (missing '}')")])

    def test_misspelled_keywords(self):
        self.assertIn("did you mean 'while'?", errors_of("whiel x < 3 { }")[0][1])
        self.assertIn("did you mean 'print'?", errors_of("pritn 5;")[0][1])
        self.assertIn("did you mean 'return'?", errors_of("func f() { retrun 1; }")[0][1])

    def test_words_from_other_languages(self):
        self.assertIn("'else if'", errors_of("if 1 { } elif 2 { }")[0][1])
        self.assertIn("no declarations", errors_of("let x = 5;")[0][1])
        self.assertIn("'func'", errors_of("def f() { }")[0][1])

    def test_assignment_in_a_condition(self):
        self.assertIn("use '=='", errors_of("if x = 1 { print x; }")[0][1])

    def test_else_without_if(self):
        self.assertIn("'else' without an 'if'", errors_of("x = 1;\nelse { }")[0][1])

    def test_too_many_errors_stops_early(self):
        src = "\n".join(f"x{i} = " for i in range(50))
        self.assertLessEqual(len(errors_of(src)), 20)

    def test_valid_programs_are_unaffected(self):
        self.assertEqual(errors_of("x = 1;\nif x { print x; } else { print 0; }"), [])


class SemanticRecoveryTests(unittest.TestCase):
    def test_every_undefined_name_is_reported(self):
        errs = errors_of("print a;\nprint b;\nprint c();")
        self.assertEqual([line for line, _ in errs], [1, 2, 3])

    def test_a_name_is_reported_once_per_scope(self):
        self.assertEqual(len(errors_of("print a;\nprint a + 1;")), 1)

    def test_did_you_mean_a_known_name(self):
        self.assertIn("did you mean 'count'?", errors_of("count = 0;\nprint cout;")[0][1])
        self.assertIn("did you mean 'total'?", errors_of("total = 1;\nfunc f() { return totl; }\nprint f();")[0][1])
        self.assertIn("did you mean 'square'?", errors_of("func square(x) { return x * x; }\nprint sqare(3);")[0][1])
        self.assertIn("did you mean 'len'?", errors_of("print lenght([1]);")[0][1])

    def test_names_from_other_languages(self):
        self.assertIn("no booleans", errors_of("x = true;")[0][1])
        self.assertIn("len(a)", errors_of("print size([1]);")[0][1])

    def test_misplaced_statements_are_all_reported(self):
        errs = errors_of("break;\nreturn 1;\nprint nope;")
        self.assertEqual([line for line, _ in errs], [1, 2, 3])

    def test_errors_come_sorted_by_line(self):
        src = "func f() { return missing; }\nprint other;\nprint f(1);"
        self.assertEqual([line for line, _ in errors_of(src)], [1, 2, 3])


class CompoundAssignmentTests(unittest.TestCase):
    def test_all_operators(self):
        self.assertEqual(run_source("x = 20; x += 5; print x; x -= 3; print x; x *= 2; print x; "
                                    "x /= 4; print x; x %= 7; print x;"), ["25", "22", "44", "11", "4"])

    def test_indexed_and_nested(self):
        src = "a = [1, [2, 3]];\na[0] += 10;\na[1][1] *= 5;\nprint a;"
        self.assertEqual(run_source(src), ["[11, [2, 15]]"])

    def test_in_a_for_loop(self):
        self.assertEqual(run_source("for i = 0; i < 6; i += 2 { print i; }"), ["0", "2", "4"])

    def test_same_as_writing_it_out(self):
        self.assertEqual(parse(tokenize("x += y * 2;")), parse(tokenize("x = x + y * 2;")))


class LintTests(unittest.TestCase):
    def test_errors_and_warnings_without_running(self):
        r = lint("x = 1\nprint y;")
        self.assertEqual([(e["stage"], e["line"]) for e in r["errors"]], [("parse", 1)])
        r = lint("x = 1;\nunused = 2;\nprint x;")
        self.assertEqual(r["errors"], [])
        self.assertEqual([(w["code"], w["line"]) for w in r["warnings"]], [("unused", 2)])

    def test_inputs_are_known_names(self):
        self.assertEqual(lint("print n;", predefined=["n"])["errors"], [])
        self.assertEqual(lint("print n;")["errors"][0]["stage"], "semantic")

    def test_an_infinite_loop_is_fine_since_nothing_runs(self):
        self.assertEqual(lint("while 1 { }"), {"errors": [], "warnings": []})


if __name__ == "__main__":
    unittest.main()
