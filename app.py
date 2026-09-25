"""MiniLang web frontend: a thin Flask layer over the compiler.

    GET  /      the playground page (templates/index.html + static/)
    POST /run   body {"source": "..."}  ->  JSON with tokens, AST, bytecode,
                output and, if a stage failed, the error with its line number

Run:  python app.py        then open http://127.0.0.1:5000
"""

import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from api import run_pipeline

ROOT = os.path.dirname(os.path.abspath(__file__))
EXAMPLES_DIR = os.path.join(ROOT, "examples")
DEFAULT_EXAMPLE = "demo.ml"  # variables, arithmetic, if/else, while and print

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000  # reject request bodies over 1 MB


def load_examples():
    examples = []
    for name in sorted(os.listdir(EXAMPLES_DIR)):
        if name.endswith(".ml"):
            with open(os.path.join(EXAMPLES_DIR, name), encoding="utf-8") as f:
                examples.append({"name": name, "source": f.read()})
    examples.sort(key=lambda e: e["name"] != DEFAULT_EXAMPLE)  # default first
    return examples


@app.get("/")
def index():
    examples = load_examples()
    return render_template("index.html", examples=examples, sample=examples[0]["source"])


@app.post("/run")
def run():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("source"), str):
        return jsonify(error='expected a JSON object like {"source": "print 1;"}'), 400

    # lexer -> parser -> compiler (+ optimizer) -> VM. Any MiniLang error is caught
    # inside run_pipeline and returned as result["error"] = {stage, message, line}.
    result = run_pipeline(body["source"], optimize=True, trace=True)
    return jsonify(result)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="request body is larger than 1 MB"), 413


@app.errorhandler(HTTPException)
def http_error(err):
    return jsonify(error=err.description), err.code


@app.errorhandler(Exception)
def unexpected(err):
    # Last-resort safety net: a bug comes back as JSON the page can show,
    # never as an HTML stack trace. The full traceback goes to the terminal.
    app.logger.exception("unexpected error while handling %s", request.path)
    return jsonify(error="internal server error (details are in the terminal running app.py)"), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
