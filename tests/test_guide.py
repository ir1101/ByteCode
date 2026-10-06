"""The language guide: every lesson renders, and every example does what the lesson says."""
import html
import re
import unittest

from tests.helpers import ROOT  # noqa: F401  (sets up sys.path)
from api import run_pipeline
from app import app
from guide import LESSONS, LESSONS_BY_SLUG, run_example
from levels import LEVELS_BY_ID

FIGURE = re.compile(r'<figure class="ex"(?: data-expect="(\w+)")?>(.*?)</figure>', re.S)
TEXTAREA = re.compile(r'<textarea[^>]*>(.*?)</textarea>', re.S)
STDIN = re.compile(r'<label class="ex-stdin">.*?value="([^"]*)"', re.S)


def examples_in(page):
    """(code, stdin, expected error stage or "") for every example on a lesson page."""
    found = []
    for expect, body in FIGURE.findall(page):
        code = html.unescape(TEXTAREA.search(body).group(1))
        stdin = STDIN.search(body)
        found.append((code, html.unescape(stdin.group(1)) if stdin else "", expect))
    return found


class LessonPagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client = app.test_client()
        cls.pages = {}
        for lesson in LESSONS:
            resp = client.get(f"/learn/language/{lesson.slug}")
            cls.pages[lesson.slug] = (resp.status_code, resp.get_data(as_text=True))

    def test_every_lesson_renders(self):
        for lesson in LESSONS:
            with self.subTest(lesson=lesson.slug):
                status, page = self.pages[lesson.slug]
                self.assertEqual(status, 200)
                self.assertIn(str(html.escape(lesson.title, quote=False)), page)
                self.assertIn("guide.js", page)

    def test_every_lesson_teaches_by_example(self):
        for lesson in LESSONS:
            with self.subTest(lesson=lesson.slug):
                page = self.pages[lesson.slug][1]
                self.assertGreaterEqual(len(examples_in(page)), 3)
                self.assertIn('class="remember"', page)
                self.assertIn('class="exercise"', page)
                self.assertIn("Show a solution", page)

    def test_every_example_does_what_the_lesson_says(self):
        # Examples run as the page renders, so this checks the real compiler's behaviour:
        # an ordinary example must run cleanly, and one that fails "on purpose" must fail
        # at exactly the stage the lesson is about.
        for lesson in LESSONS:
            for code, stdin, expect in examples_in(self.pages[lesson.slug][1]):
                with self.subTest(lesson=lesson.slug, code=code.splitlines()[0]):
                    r = run_pipeline(code, stdin=stdin, max_steps=100_000)
                    if expect:
                        self.assertTrue(r["errors"], "expected an error")
                        self.assertEqual(r["errors"][0]["stage"], expect)
                    else:
                        self.assertEqual(r["errors"], [])
                        self.assertTrue(r["output"], "an example should print something")

    def test_the_page_shows_the_real_output(self):
        page = self.pages["lists"][1]
        self.assertIn("[2, 3, 5, 7, 11]", page)
        self.assertIn("index 3 is out of range", page)
        self.assertIn("on purpose", page)

    def test_examples_with_input_carry_it(self):
        found = examples_in(self.pages["input"][1])
        self.assertIn(("input a;\ninput b;\nprint a + b;", "20 22", ""), found)

    def test_examples_open_in_the_playground(self):
        page = self.pages["first-program"][1]
        self.assertIn('href="/play?code=print+42;', page)

    def test_lessons_link_to_each_other_and_to_the_game(self):
        for i, lesson in enumerate(LESSONS):
            with self.subTest(lesson=lesson.slug):
                page = self.pages[lesson.slug][1]
                if i + 1 < len(LESSONS):
                    self.assertIn(f"/learn/language/{LESSONS[i + 1].slug}", page)
                self.assertIn(lesson.level, LEVELS_BY_ID)
                self.assertIn(f"/play#level={lesson.level}", page)


class GuideRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_hub_lists_lessons_before_chapters(self):
        page = self.client.get("/learn").get_data(as_text=True)
        positions = [page.index(f"/learn/language/{lesson.slug}") for lesson in LESSONS]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(page.index('id="language"'), page.index('id="compiler"'))

    def test_language_index_redirects_to_the_hub(self):
        resp = self.client.get("/learn/language")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/learn#language"))

    def test_unknown_lesson(self):
        self.assertEqual(self.client.get("/learn/language/nope").status_code, 404)

    def test_landing_mentions_the_lessons(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn(f"{len(LESSONS)} lessons on writing MiniLang", page)

    def test_run_without_trace(self):
        r = self.client.post("/run", json={"source": "print 1;", "trace": False}).get_json()
        self.assertIsNone(r["trace"])
        self.assertEqual(r["output"], ["1"])


class RunExampleTests(unittest.TestCase):
    def test_results_are_cached_and_complete(self):
        first = run_example("print 6 * 7;\n")
        self.assertIs(first, run_example("print 6 * 7;"))   # surrounding blank lines don't matter
        self.assertEqual((first["output"], first["output_text"], first["lines"]), (["42"], "42", 1))

    def test_an_endless_loop_stops_quickly(self):
        r = run_example("while 1 { }")
        self.assertEqual(r["errors"][0]["stage"], "runtime")
        self.assertIn("step limit", r["errors"][0]["message"])

    def test_lesson_index(self):
        self.assertEqual(len(LESSONS), len(LESSONS_BY_SLUG))
        self.assertEqual(LESSONS[0].slug, "first-program")


if __name__ == "__main__":
    unittest.main()
