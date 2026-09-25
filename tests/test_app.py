import unittest

from tests.helpers import ROOT  # noqa: F401  (sets up sys.path)
from app import app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_index_serves_page_with_sample_program(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="run"', html)
        self.assertIn("codemirror", html)
        self.assertIn("fact = fact * i;", html)             # demo.ml pre-filled in the editor
        self.assertIn('<option value="functions.ml">', html)

    def test_static_files(self):
        for path in ("/static/app.js", "/static/style.css"):
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

    def test_each_stage_error_is_returned_with_its_line(self):
        cases = [
            ("x = 1;\ny = 2 @ 3;", "lex", 2),
            ("x = 1\nprint x;", "parse", 1),
            ("print nope();", "compile", 1),
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

    def test_oversized_body_rejected(self):
        resp = self.client.post("/run", data="x" * 1_100_000, content_type="application/json")
        self.assertEqual(resp.status_code, 413)


if __name__ == "__main__":
    unittest.main()
