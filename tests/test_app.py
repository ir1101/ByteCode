import os
import unittest
from markupsafe import escape   # the same escaping Jinja uses

from tests.helpers import ROOT  # sets up sys.path
from app import app, project_stats
from learn import CHAPTERS
from levels import LEVELS


class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_playground_serves_page_with_sample_program(self):
        resp = self.client.get("/play")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="run"', html)
        self.assertIn("codemirror", html)
        self.assertIn("fact = fact * i;", html)             # demo.ml pre-filled in the editor
        self.assertIn('<option value="functions.ml">', html)

    def test_static_files(self):
        for path in ("/static/app.js", "/static/style.css", "/static/theme.css", "/static/site.css",
                     "/static/landing.js", "/static/game.js"):
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 200)
                resp.close()

    def test_run_returns_all_four_stages(self):
        resp = self.client.post("/run", json={"source": "x = 6;\nprint x * 7;"})
        self.assertEqual(resp.status_code, 200)
        r = resp.get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["tokens"][0], {"type": "IDENT", "value": "x", "line": 1})
        self.assertIn("Assign(name='x')", r["ast_dump"])
        self.assertEqual([ins["op"] for ins in r["bytecode"]][-2:], ["PRINT", "HALT"])
        self.assertEqual(r["output"], ["42"])
        self.assertTrue(r["trace"])                        # the page's step-through view

    def test_run_includes_symbols_warnings_and_ir(self):
        r = self.client.post("/run", json={"source": "x = 1;\nunused = 2;\nprint x;"}).get_json()
        self.assertEqual([g["name"] for g in r["symbols"]["globals"]], ["x", "unused"])
        self.assertEqual([(w["line"], w["code"]) for w in r["warnings"]], [(2, "unused")])
        self.assertGreaterEqual(r["ir"]["stats"]["blocks"], 1)
        self.assertIn("print 1", r["ir"]["procedures"][0]["blocks"][0]["optimized"])

    def test_page_has_symbols_and_ir_tabs(self):
        html = self.client.get("/play").get_data(as_text=True)
        self.assertIn('id="tab-symbols"', html)
        self.assertIn('id="tab-ir"', html)
        self.assertIn('<option value="arrays.ml">', html)
        self.assertIn('<option value="dataflow.ml">', html)

    def test_each_stage_error_is_returned_with_its_line(self):
        cases = [
            ("x = 1;\ny = 2 @ 3;", "lex", 2),
            ("x = 1\nprint x;", "parse", 1),
            ("print nope();", "semantic", 1),
            ("print 1;\nprint 1 / 0;", "runtime", 2),
        ]
        for source, stage, line in cases:
            with self.subTest(stage=stage):
                resp = self.client.post("/run", json={"source": source})
                self.assertEqual(resp.status_code, 200)
                err = resp.get_json()["error"]
                self.assertEqual((err["stage"], err["line"]), (stage, line))
                self.assertTrue(err["message"])

    def test_runtime_error_keeps_earlier_output(self):
        r = self.client.post("/run", json={"source": "print 1;\nprint 1 / 0;"}).get_json()
        self.assertEqual(r["output"], ["1"])

    def test_bad_requests_get_json_errors(self):
        for kwargs in ({"data": "not json", "content_type": "application/json"},
                       {"json": {"code": "print 1;"}},
                       {"json": {"source": 5}},
                       {"json": ["print 1;"]}):
            with self.subTest(kwargs=kwargs):
                resp = self.client.post("/run", **kwargs)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("source", resp.get_json()["error"])

    def test_unknown_route_and_wrong_method(self):
        self.assertEqual(self.client.get("/nope").status_code, 404)
        self.assertEqual(self.client.get("/run").status_code, 405)
        self.assertIn("error", self.client.get("/nope").get_json())

    def test_a_browser_gets_a_404_page_not_json(self):
        resp = self.client.get("/nope", headers={"Accept": "text/html,application/xhtml+xml"})
        self.assertEqual(resp.status_code, 404)
        self.assertIn("Page not found", resp.get_data(as_text=True))

    def test_page_embeds_levels_without_solutions(self):
        html = self.client.get("/play").get_data(as_text=True)
        self.assertIn('id="levels-data"', html)
        self.assertIn("Count to n", html)
        self.assertIn("game.js", html)
        self.assertNotIn("references", html)

    def test_run_with_level_uses_example_inputs(self):
        r = self.client.post("/run", json={"level": "c1", "source": "print n;"}).get_json()
        self.assertEqual(r["output"], ["5"])
        self.assertEqual(r["harness"]["inputs"], {"n": 5})
        self.assertEqual(r["trace"][0]["variables"], {"n": 5})  # the input is visible in the stepper

    def test_run_with_function_level_appends_test_code(self):
        r = self.client.post("/run", json={"level": "c6", "source": "func fact(n) { return n; }"}).get_json()
        self.assertEqual(r["output"], ["5"])
        self.assertEqual(r["harness"]["epilogue"], "print fact(5);")

    def test_run_with_unknown_level(self):
        self.assertEqual(self.client.post("/run", json={"level": "zz", "source": ""}).status_code, 404)

    def test_check_scores_a_solution(self):
        r = self.client.post("/check", json={"level": "c2", "source": "print n * (n + 1) / 2;"}).get_json()
        self.assertTrue(r["passed"])
        self.assertEqual(r["stars"], [True, True, True])
        self.assertTrue(all(t["passed"] for t in r["tests"]))

    def test_check_reports_failures(self):
        r = self.client.post("/check", json={"level": "c2", "source": "print 55;"}).get_json()
        self.assertFalse(r["passed"])
        failing = [t for t in r["tests"] if not t["passed"]]
        self.assertTrue(failing)
        self.assertEqual(failing[0]["output"], ["55"])

    def test_check_bad_requests(self):
        self.assertEqual(self.client.post("/check", json={"level": "nope", "source": ""}).status_code, 404)
        self.assertEqual(self.client.post("/check", json={"source": "print 1;"}).status_code, 400)
        self.assertEqual(self.client.post("/check", json={"level": "c1"}).status_code, 400)
        self.assertEqual(self.client.post("/check", data="x", content_type="application/json").status_code, 400)

    def test_lan_addresses_are_real_network_addresses(self):
        from app import lan_addresses
        for ip in lan_addresses():
            parts = ip.split(".")
            self.assertEqual(len(parts), 4, ip)
            self.assertFalse(ip.startswith(("127.", "0.", "169.254.")), ip)

    def test_lint_reports_problems_without_running(self):
        r = self.client.post("/lint", json={"source": "x = 1\ny = 2\nprint q;"}).get_json()
        self.assertEqual([(e["stage"], e["line"]) for e in r["errors"]], [("parse", 1), ("parse", 2)])
        r = self.client.post("/lint", json={"source": "x = 0;\nx = 1;\nprint x;"}).get_json()
        self.assertEqual(r["errors"], [])
        self.assertEqual([w["code"] for w in r["warnings"]], ["dead-store"])

    def test_lint_in_a_level_knows_its_inputs_and_test_code(self):
        r = self.client.post("/lint", json={"level": "c1", "source": "print n;"}).get_json()
        self.assertEqual(r, {"errors": [], "warnings": []})
        # fact() isn't written yet: the test code that calls it isn't the player's problem yet
        r = self.client.post("/lint", json={"level": "c6", "source": "# nothing yet\n"}).get_json()
        self.assertEqual(r["errors"], [])

    def test_lint_bad_requests(self):
        self.assertEqual(self.client.post("/lint", json={"code": "x"}).status_code, 400)
        self.assertEqual(self.client.post("/lint", json={"level": "zz", "source": ""}).status_code, 404)

    def test_run_returns_every_parse_error(self):
        r = self.client.post("/run", json={"source": "x = 1\ny = 2\nprint x + y;"}).get_json()
        self.assertEqual([e["line"] for e in r["errors"]], [1, 2])

    def test_run_with_stdin(self):
        r = self.client.post("/run", json={"source": "input a;\ninput b;\nprint a * b;", "stdin": "6 7 8"}).get_json()
        self.assertEqual(r["output"], ["42"])
        self.assertEqual(r["input"], {"values": ["6", "7", "8"], "used": 2})
        self.assertEqual(self.client.post("/run", json={"source": "print 1;", "stdin": 5}).status_code, 400)

    def test_oversized_body_rejected(self):
        resp = self.client.post("/run", data="x" * 1_100_000, content_type="application/json")
        self.assertEqual(resp.status_code, 413)


class PagesTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_landing_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        for text in ("Bytecode", "Compiler", "[Pipeline/list]", "Ishu Raj", "24BDS0255", "Muthunagai",
                     'href="/play"', 'href="/learn"', "landing.js", 'id="landing-data"'):
            with self.subTest(text=text):
                self.assertIn(text, html)
        for chapter in CHAPTERS:   # the pipeline list links every chapter
            self.assertIn(f'href="/learn/{chapter.slug}"', html)

    def test_landing_demo_program_runs(self):
        from app import LANDING_DEMO
        r = self.client.post("/run", json={"source": LANDING_DEMO}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["output"], ["120"])
        self.assertTrue(r["trace"])

    def test_project_stats_count_the_real_tests(self):
        stats = project_stats()
        suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)
        self.assertEqual(stats["tests"], suite.countTestCases())
        self.assertEqual(stats["challenges"] + stats["bug_hunts"], len(LEVELS))
        self.assertEqual(stats["max_stars"], 3 * len(LEVELS))
        self.assertGreater(stats["opcodes"], 25)
        self.assertGreater(stats["python_lines"], 1000)

    def test_learn_lists_every_chapter(self):
        html = self.client.get("/learn").get_data(as_text=True)
        for chapter in CHAPTERS:
            with self.subTest(chapter=chapter.slug):
                self.assertIn(str(escape(chapter.title)), html)
                self.assertIn(f'/learn/{chapter.slug}', html)
                self.assertIn(chapter.source, html)

    def test_chapter_page_shows_outline_and_links(self):
        for i, chapter in enumerate(CHAPTERS):
            with self.subTest(chapter=chapter.slug):
                resp = self.client.get(f"/learn/{chapter.slug}")
                self.assertEqual(resp.status_code, 200)
                html = resp.get_data(as_text=True)
                for topic in chapter.topics:
                    self.assertIn(str(escape(topic.title)), html)
                self.assertIn(f"/play?example={chapter.example}", html)   # opens the right example
                if i + 1 < len(CHAPTERS):
                    self.assertIn(f"/learn/{CHAPTERS[i + 1].slug}", html)

    def test_chapter_examples_exist(self):
        for chapter in CHAPTERS:
            with self.subTest(chapter=chapter.slug):
                self.assertTrue(os.path.exists(os.path.join(ROOT, "examples", chapter.example)))
                self.assertTrue(os.path.exists(os.path.join(ROOT, chapter.source)))

    def test_unknown_chapter(self):
        self.assertEqual(self.client.get("/learn/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
