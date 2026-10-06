"""MiniLang web frontend: a thin Flask layer over the compiler.

    GET  /               the landing page (templates/landing.html)
    GET  /play           the playground (templates/playground.html + static/app.js, game.js)
                         ?example=arrays.ml opens that example; #levels opens the level picker
    GET  /learn          the learning section: lessons on the language (guide.py), then
                         one chapter per compiler stage (learn.py)
    GET  /learn/language/<slug>   one lesson; its examples run on the server as the page renders
    GET  /learn/<slug>   one chapter on the compiler; quotes the real source and runs live demos
    POST /stage  body {"source": "...", "view": "tokens", "stdin"?: "..."}  ->  what one stage of
                 the pipeline makes of the code, as text (the chapters' demos call it)
    POST /run    body {"source": "...", "stdin"?: "3 4", "level"?: "c1", "trace"?: false}  ->  JSON with
                 tokens, AST, bytecode, output and, if a stage failed, the errors with
                 their line numbers. "stdin" holds the numbers `input` statements read.
                 With "level", the code runs on that level's example test.
    POST /check  body {"level": "c1", "source": "..."}  ->  every test of the level,
                 the score, and the stars earned (see levels.py)
    POST /lint   body {"source": "...", "level"?: "c1"}  ->  {"errors": [...], "warnings": [...]}
                 from the lexer, parser and semantic analysis only; the editor calls it
                 as you type to underline problems before you press Run

Run:  python app.py         this computer only: http://127.0.0.1:5000
      python app.py --lan   also every device on your Wi-Fi / LAN (the addresses are printed)
"""

import argparse
import glob
import os
import re
import socket

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from api import lint, run_pipeline
from guide import LESSONS, LESSONS_BY_SLUG, run_example as run_guide_example
from guide import neighbours as lesson_neighbours
from learn import CHAPTERS, CHAPTERS_BY_SLUG, VIEWS, excerpt, neighbours, slug, stage_view
from levels import LEVELS, LEVELS_BY_ID, check_level, lint_level, public_levels, run_example
from vm import BINARY_OPS

ROOT = os.path.dirname(os.path.abspath(__file__))
EXAMPLES_DIR = os.path.join(ROOT, "examples")
DEFAULT_EXAMPLE = "demo.ml"  # variables, arithmetic, if/else, while and print
REPOSITORY = "https://github.com/ir1101/ByteCode"
# The program the landing page's stack machine runs (through /run, like any other).
LANDING_DEMO = "n = 1;\nfor i = 1; i <= 5; i += 1 {\n    n *= i;\n}\nprint n;\n"

PROJECT = {
    "course": "BCSE307P · Compiler Lab",
    "guide": "Prof. Muthunagai S U",
    "team": [("Ishu Raj", "24BDS0255"), ("Parth Bagwe", "24BDS0284"),
             ("Siddiqa", "24BCE2847"), ("Tejas Sinha", "24BDS0203")],
    "repository": REPOSITORY,
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000  # reject request bodies over 1 MB
app.jinja_env.globals["run_example"] = run_guide_example   # the lessons' example macro runs code with it
app.jinja_env.globals.update(stage_view=stage_view, excerpt=excerpt)   # the chapters' demos and quotes
app.jinja_env.filters["slug"] = slug
app.jinja_env.globals["REPOSITORY"] = REPOSITORY


def load_examples():
    examples = []
    for name in sorted(os.listdir(EXAMPLES_DIR)):
        if name.endswith(".ml"):
            with open(os.path.join(EXAMPLES_DIR, name), encoding="utf-8") as f:
                examples.append({"name": name, "source": f.read()})
    examples.sort(key=lambda e: e["name"] != DEFAULT_EXAMPLE)  # default first
    return examples


def bad_request(example):
    return jsonify(error=f"expected a JSON object like {example}"), 400


def project_stats():
    """Numbers for the landing page, counted from the code itself so they never go stale."""
    lines = 0
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        with open(path, encoding="utf-8") as f:
            lines += sum(1 for line in f if line.strip())
    tests = 0
    for path in glob.glob(os.path.join(ROOT, "tests", "test_*.py")):
        with open(path, encoding="utf-8") as f:
            tests += len(re.findall(r"^\s+def test_", f.read(), re.MULTILINE))
    with open(os.path.join(ROOT, "vm.py"), encoding="utf-8") as f:
        opcodes = set(re.findall(r'op == "([A-Z_]+)"', f.read())) | BINARY_OPS
    return {
        "python_lines": lines,
        "tests": tests,
        "opcodes": len(opcodes),
        "challenges": sum(1 for lv in LEVELS if lv.track == "challenge"),
        "bug_hunts": sum(1 for lv in LEVELS if lv.track == "bug"),
        "max_stars": len(LEVELS) * 3,
        "examples": len(load_examples()),
        "chapters": len(CHAPTERS),
        "lessons": len(LESSONS),
    }


@app.get("/")
def landing():
    return render_template("landing.html", stats=project_stats(), project=PROJECT, chapters=CHAPTERS,
                           demo=LANDING_DEMO)


@app.get("/play")
def playground():
    examples = load_examples()
    return render_template("playground.html", examples=examples, sample=examples[0]["source"],
                           levels=public_levels())


@app.get("/learn")
def learn():
    return render_template("learn.html", chapters=CHAPTERS, lessons=LESSONS, project=PROJECT, section="learn")


@app.get("/learn/language")
def language():
    return redirect(url_for("learn") + "#language")


@app.get("/learn/language/<slug>")
def lesson(slug):
    found = LESSONS_BY_SLUG.get(slug)
    if found is None:
        abort(404, description=f"There is no lesson called {slug!r}.")
    previous, following = lesson_neighbours(found)
    return render_template(f"guide/{found.slug}.html", lesson=found, number=LESSONS.index(found) + 1,
                           lessons=LESSONS, previous=previous, following=following,
                           level=LEVELS_BY_ID.get(found.level), project=PROJECT, section="learn")


@app.get("/learn/<slug>")
def chapter(slug):
    found = CHAPTERS_BY_SLUG.get(slug)
    if found is None:
        abort(404, description=f"There is no chapter called {slug!r}.")
    previous, following = neighbours(found)
    # A written chapter has its own template; otherwise its outline is shown.
    template = f"chapters/{found.slug}.html" if found.written else "chapter.html"
    return render_template(template, chapter=found, number=CHAPTERS.index(found) + 1,
                           previous=previous, following=following, chapters=CHAPTERS, project=PROJECT,
                           section="learn")


@app.post("/run")
def run():
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or not isinstance(body.get("source"), str)
            or not isinstance(body.get("stdin", ""), str)):
        return bad_request('{"source": "input x; print x * 2;", "stdin": "21"}')

    level_id = body.get("level")
    if level_id is not None:
        level = LEVELS_BY_ID.get(level_id) if isinstance(level_id, str) else None
        if level is None:
            return jsonify(error=f"unknown level {level_id!r}"), 404
        return jsonify(run_example(level, body["source"]))   # a level brings its own input

    # lexer -> parser -> semantic -> types -> compiler (+ optimizer) -> VM. Any MiniLang
    # error is caught inside run_pipeline and returned as result["errors"].
    result = run_pipeline(body["source"], optimize=True, trace=body.get("trace", True) is not False,
                          stdin=body.get("stdin", ""))
    return jsonify(result)


@app.post("/stage")
def stage():
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or not isinstance(body.get("source"), str)
            or body.get("view") not in VIEWS or not isinstance(body.get("stdin", ""), str)):
        return bad_request('{"source": "print 1;", "view": "tokens"}')
    if len(body["source"]) > 20_000:
        return jsonify(error="a demo's code must be under 20,000 characters"), 400
    return jsonify(stage_view(body["source"], body["view"], body.get("stdin", "")))


@app.post("/check")
def check():
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or not isinstance(body.get("source"), str)
            or not isinstance(body.get("level"), str)):
        return bad_request('{"level": "c1", "source": "print 1;"}')
    level = LEVELS_BY_ID.get(body["level"])
    if level is None:
        return jsonify(error=f"unknown level {body['level']!r}"), 404
    return jsonify(check_level(level, body["source"]))


@app.post("/lint")
def lint_route():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("source"), str):
        return bad_request('{"source": "print 1;"}')
    level_id = body.get("level")
    if level_id is not None:
        level = LEVELS_BY_ID.get(level_id) if isinstance(level_id, str) else None
        if level is None:
            return jsonify(error=f"unknown level {level_id!r}"), 404
        return jsonify(lint_level(level, body["source"]))
    return jsonify(lint(body["source"]))


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="request body is larger than 1 MB"), 413


def wants_page():
    """A browser asking for a page gets HTML; fetch() and API clients get JSON."""
    return request.method == "GET" and "text/html" in request.headers.get("Accept", "")


@app.errorhandler(HTTPException)
def http_error(err):
    if wants_page():
        return render_template("not_found.html", code=err.code, message=err.description,
                               project=PROJECT), err.code
    return jsonify(error=err.description), err.code


@app.errorhandler(Exception)
def unexpected(err):
    # Last-resort safety net: a bug comes back as JSON the page can show,
    # never as an HTML stack trace. The full traceback goes to the terminal.
    app.logger.exception("unexpected error while handling %s", request.path)
    return jsonify(error="internal server error (details are in the terminal running app.py)"), 500


def lan_addresses():
    """This machine's IPv4 addresses on the local network, for the startup message."""
    found = set()
    try:
        # Connecting a UDP socket sends nothing; it just makes the OS pick the
        # interface it would use to reach the network, revealing our LAN address.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith(("127.", "0.", "169.254.")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Serve the MiniLang playground.")
    ap.add_argument("--lan", action="store_true",
                    help="let other devices on your local network open the playground")
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args(argv)

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    print(f"MiniLang on this computer: http://127.0.0.1:{args.port}  "
          f"(playground at /play, learning section at /learn)")
    if args.lan:
        addresses = lan_addresses()
        if addresses:
            print("Other devices on the same network can open:")
            for ip in addresses:
                print(f"    http://{ip}:{args.port}")
        else:
            print("No network connection found, so only this computer can reach it.")
    app.run(host=host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
