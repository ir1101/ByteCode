import json
import unittest

from tests.helpers import ROOT  # noqa: F401  (sets up sys.path)
from levels import LEVELS, LEVELS_BY_ID, changed_lines, check_level, public_levels, run_example


def stars(level_id, source):
    return check_level(LEVELS_BY_ID[level_id], source)["stars"]


class LevelDataTests(unittest.TestCase):
    def test_ids_are_unique_and_tracks_are_known(self):
        self.assertEqual(len(LEVELS), len(LEVELS_BY_ID))
        self.assertEqual({lv.track for lv in LEVELS}, {"challenge", "bug"})

    def test_every_reference_earns_three_stars(self):
        for lv in LEVELS:
            for ref in lv.references:
                with self.subTest(level=lv.id):
                    result = check_level(lv, ref)
                    self.assertEqual(result["stars"], [True, True, True], result["tests"])

    def test_every_level_has_several_tests(self):
        for lv in LEVELS:
            with self.subTest(level=lv.id):
                self.assertGreaterEqual(len(lv.tests), 3)
                self.assertEqual(len(lv.expected), len(lv.tests))

    def test_no_starter_passes(self):
        for lv in LEVELS:
            with self.subTest(level=lv.id):
                self.assertFalse(check_level(lv, lv.starter)["passed"])

    def test_bug_hunts_fail_at_their_stage(self):
        for lv in (lv for lv in LEVELS if lv.track == "bug"):
            with self.subTest(level=lv.id):
                result = check_level(lv, lv.starter)
                errors = [t["error"]["stage"] for t in result["tests"] if t["error"]]
                if lv.bug_stage == "logic":
                    self.assertEqual(errors, [])           # runs cleanly, just prints the wrong thing
                else:
                    self.assertIn(lv.bug_stage, errors)

    def test_bug_hunt_starters_show_the_bug_on_the_example(self):
        # Pressing Run on an unchanged bug hunt should already reveal the problem.
        for lv in (lv for lv in LEVELS if lv.track == "bug"):
            with self.subTest(level=lv.id):
                result = run_example(lv, lv.starter)
                if lv.bug_stage == "logic":
                    self.assertNotEqual(result["output"], lv.expected[0])
                else:
                    self.assertEqual(result["error"]["stage"], lv.bug_stage)


class ScoringTests(unittest.TestCase):
    def test_hard_coded_answer_fails(self):
        self.assertEqual(stars("c2", "print 55;"), [False, False, False])  # right for n = 10 only

    def test_sum_loop_misses_size_and_speed(self):
        loop = "total = 0;\nfor i = 1; i <= n; i = i + 1 { total = total + i; }\nprint total;"
        self.assertEqual(stars("c2", loop), [True, False, False])

    def test_recursive_fib_is_correct_and_small_but_slow(self):
        recursive = "func fib(n) {\n    if n < 2 { return n; }\n    return fib(n - 1) + fib(n - 2);\n}\n"
        self.assertEqual(stars("c7", recursive), [True, True, False])

    def test_size_and_speed_stars_need_passing_tests(self):
        self.assertEqual(stars("c2", ""), [False, False, False])  # tiny and fast, but wrong

    def test_bug_hunt_rewrite_loses_minimal_fix_star(self):
        rewrite = "total = 0;\nfor i = 1; i <= n; i = i + 1 { total = total + i * i; }\nprint total;"
        self.assertEqual(stars("b7", rewrite), [True, False, True])

    def test_metrics_and_par_are_reported(self):
        result = check_level(LEVELS_BY_ID["c1"], LEVELS_BY_ID["c1"].references[0])
        self.assertEqual(result["metrics"]["size"], result["par"]["size"])
        self.assertEqual(result["metrics"]["steps"], result["par"]["steps"])
        self.assertIsNone(result["metrics"]["changes"])
        self.assertEqual(len(result["criteria"]), 3)

    def test_infinite_loop_is_cut_off(self):
        result = check_level(LEVELS_BY_ID["c1"], "while 1 { }")
        self.assertFalse(result["passed"])
        self.assertIn("step limit", result["tests"][0]["error"]["message"])


class TestCodeErrorTests(unittest.TestCase):
    def test_missing_function_is_blamed_on_test_code(self):
        result = check_level(LEVELS_BY_ID["c6"], "x = 1;")
        err = result["tests"][0]["error"]
        self.assertTrue(err["in_test_code"])
        self.assertIn("undefined function 'fact'", err["message"])
        self.assertIn("print fact(5);", err["message"])

    def test_errors_in_player_code_keep_their_line(self):
        err = check_level(LEVELS_BY_ID["c6"], "func fact(n) {\n  return n\n}")["tests"][0]["error"]
        self.assertEqual(err["line"], 2)
        self.assertNotIn("in_test_code", err)

    def test_inputs_do_not_shift_line_numbers(self):
        err = run_example(LEVELS_BY_ID["c1"], "x = 1;\nprint y;")["error"]
        self.assertEqual((err["stage"], err["line"]), ("runtime", 2))


class ChangedLinesTests(unittest.TestCase):
    def test_identical_and_cosmetic_changes(self):
        code = "x = 1;\nprint x;\n"
        self.assertEqual(changed_lines(code, code), 0)
        self.assertEqual(changed_lines(code, "x  =  1;   # note\n\n    print x;"), 0)

    def test_replaced_added_and_removed_lines(self):
        before = "a = 1;\nb = 2;\nprint a;\n"
        self.assertEqual(changed_lines(before, "a = 1;\nb = 3;\nprint a;\n"), 1)
        self.assertEqual(changed_lines(before, "a = 1;\nb = 2;\nc = 3;\nprint a;\n"), 1)
        self.assertEqual(changed_lines(before, "a = 1;\nprint a;\n"), 1)
        self.assertEqual(changed_lines(before, ""), 3)


class PublicDataTests(unittest.TestCase):
    def test_public_levels_never_leak_references(self):
        text = json.dumps(public_levels())
        self.assertNotIn("references", text)
        for lv in LEVELS:
            for ref in lv.references:
                if ref.strip() not in lv.starter:  # bug-hunt fixes share lines with starters
                    self.assertNotIn(json.dumps(ref)[1:-1], text, lv.id)

    def test_public_level_shape(self):
        first = public_levels()[0]
        for key in ("id", "code", "track", "title", "brief", "starter", "hint", "example", "criteria", "par", "tests_count"):
            self.assertIn(key, first)
        self.assertEqual(first["example"]["expected"], ["1", "2", "3", "4", "5"])


if __name__ == "__main__":
    unittest.main()
