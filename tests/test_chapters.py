"""The compiler chapters: every chapter is written, its quotes are real, and its demos do what it says."""
import html
import os
import re
import unittest

from tests.helpers import ROOT
from app import app
from learn import CHAPTERS, VIEWS, excerpt, highlight_python, slug, stage_view
from semantic import analyze
from lexer import tokenize
from parser import parse

DEMO = re.compile(r'<figure class="ex is-stage" data-view="(\w+)"(?: data-expect="(\w+)")?>(.*?)</figure>', re.S)
TEXTAREA = re.compile(r"<textarea[^>]*>(.*?)</textarea>", re.S)
STDIN = re.compile(r'<label class="ex-stdin">.*?value="([^"]*)"', re.S)
QUOTE = re.compile(r'<span class="src-file">([^<]+)</span>.*?#L(\d+)-L(\d+)"', re.S)


class ChapterPagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client = app.test_client()
        cls.pages = {c.slug: client.get(f"/learn/{c.slug}") for c in CHAPTERS}

    def page(self, chapter):
        return self.pages[chapter.slug].get_data(as_text=True)

    def test_every_chapter_is_written(self):
        for chapter in CHAPTERS:
            with self.subTest(chapter=chapter.slug):
                self.assertEqual(chapter.status, "ready")
                self.assertEqual(self.pages[chapter.slug].status_code, 200)

    def test_every_topic_has_its_own_section(self):
        for chapter in CHAPTERS:
            page = self.page(chapter)
            for topic in chapter.topics:
                with self.subTest(chapter=chapter.slug, topic=topic.title):
                    self.assertIn(f'<h2 id="{slug(topic.title)}">', page)    # the section
                    self.assertIn(f'href="#{slug(topic.title)}"', page)      # its contents entry

    def test_every_chapter_quotes_its_source_and_has_demos(self):
        for chapter in CHAPTERS:
            with self.subTest(chapter=chapter.slug):
                page = self.page(chapter)
                files = [path for path, _, _ in QUOTE.findall(page)]
                self.assertIn(chapter.source, files)
                self.assertGreaterEqual(len(DEMO.findall(page)), 4)
                self.assertIn('class="remember"', page)
                self.assertIn('class="exercise"', page)

    def test_quotes_match_the_files_they_come_from(self):
        for chapter in CHAPTERS:
            for path, first, last in QUOTE.findall(self.page(chapter)):
                with self.subTest(chapter=chapter.slug, path=path, lines=first):
                    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
                        lines = f.read().split("\n")
                    self.assertLessEqual(int(last), len(lines))
                    self.assertTrue(lines[int(first) - 1].strip())    # starts on real code, not a blank line

    def test_every_demo_does_what_the_chapter_says(self):
        for chapter in CHAPTERS:
            for view, expect, body in DEMO.findall(self.page(chapter)):
                code = html.unescape(TEXTAREA.search(body).group(1))
                stdin = STDIN.search(body)
                with self.subTest(chapter=chapter.slug, view=view, code=code.splitlines()[0]):
                    r = stage_view(code, view, html.unescape(stdin.group(1)) if stdin else "")
                    if expect:
                        self.assertTrue(r["errors"], "expected an error")
                        self.assertEqual(r["errors"][0]["stage"], expect)
                    else:
                        self.assertEqual(r["errors"], [])
                        self.assertTrue(r["text"].strip())

    def test_demos_open_on_the_right_playground_tab(self):
        page = self.page(CHAPTERS[0])    # the lexer: token demos
        self.assertIn("tab=tokens", page)


class ExcerptTests(unittest.TestCase):
    def test_a_method_by_name(self):
        e = excerpt("lexer.py", "Lexer.read_word")
        self.assertTrue(e["code"].startswith("def read_word(self):"))
        with open(os.path.join(ROOT, "lexer.py"), encoding="utf-8") as f:
            self.assertEqual(f.read().split("\n")[e["first"] - 1].strip(), "def read_word(self):")
        self.assertEqual(len(e["gutter"].split("\n")), e["code"].count("\n") + 1)

    def test_part_of_a_function(self):
        e = excerpt("vm.py", "VM.run", start='elif op == "CALL":', end="self.stack.append(value)")
        self.assertTrue(e["code"].startswith('elif op == "CALL":'))
        self.assertIn('elif op == "RET":', e["code"])

    def test_a_broken_quote_fails_loudly(self):
        with self.assertRaises(LookupError):
            excerpt("lexer.py", "Lexer.no_such_method")
        with self.assertRaises(LookupError):
            excerpt("lexer.py", "Lexer.read_word", start="no such text")

    def test_highlighting_escapes_and_marks_up(self):
        out = str(highlight_python('def f(x):\n    return x < 2  # "small"\n'))
        self.assertIn('<span class="py-kw">def</span>', out)
        self.assertIn('<span class="py-defname">f</span>', out)
        self.assertIn("x &lt; <span class=\"py-num\">2</span>", out)
        self.assertIn('<span class="py-com"># &quot;small&quot;</span>', out)


class StageViewTests(unittest.TestCase):
    def test_every_view(self):
        code = "func sq(x) { return x * x; }\nn = 3;\nprint sq(n) + 1;"
        for view in VIEWS:
            with self.subTest(view=view):
                r = stage_view(code, view)
                self.assertEqual(r["errors"], [])
                self.assertTrue(r["text"])
        self.assertEqual(stage_view(code, "output")["text"], "10")

    def test_a_view_stops_at_its_stage(self):
        # The lexer doesn't care that x is undefined; semantic analysis does.
        self.assertEqual(stage_view("print x;", "tokens")["errors"], [])
        self.assertEqual(stage_view("print x;", "symbols")["errors"][0]["stage"], "semantic")

    def test_trace_is_trimmed_and_shows_output_under_its_print(self):
        long = stage_view("i = 0;\nwhile i < 100 { i += 1; }\nprint i;", "trace")["text"].split("\n")
        self.assertTrue(long[-1].startswith("... and "))
        short = stage_view("print 7;", "trace")["text"].split("\n")
        self.assertIn("PRINT", short[1])
        self.assertEqual(short[2].split(), ["prints", "7"])

    def test_stage_endpoint(self):
        client = app.test_client()
        r = client.post("/stage", json={"source": "x = 1;", "view": "tokens"}).get_json()
        self.assertEqual(r["label"], "Tokens")
        self.assertIn("IDENT", r["text"])
        self.assertEqual(client.post("/stage", json={"source": "x", "view": "nope"}).status_code, 400)
        self.assertEqual(client.post("/stage", json={"source": "x" * 20_001, "view": "ast"}).status_code, 400)


class ScopeTrapReadTests(unittest.TestCase):
    def test_a_trapped_read_counts_as_reading_the_global(self):
        src = "count = 0;\nfunc bump() {\n    count = count + 1;\n    return count;\n}\nprint bump();"
        warnings = analyze(parse(tokenize(src))).to_dict()["warnings"]
        self.assertEqual([(w["line"], w["code"]) for w in warnings], [(3, "scope-trap")])   # no "unused" for line 1


if __name__ == "__main__":
    unittest.main()
