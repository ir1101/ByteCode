import io
import os
import sys

# Make the project root importable when tests run from any directory.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from compiler import compile_program  # noqa: E402
from lexer import tokenize  # noqa: E402
from optimizer import optimize as optimize_program  # noqa: E402
from parser import parse  # noqa: E402
from vm import VM  # noqa: E402


def compile_source(source, optimize=False):
    tree = parse(tokenize(source))
    return optimize_program(tree) if optimize else compile_program(tree)


def run_source(source, optimize=False):
    """Run MiniLang source through every stage and return printed lines."""
    out = io.StringIO()
    VM(compile_source(source, optimize), out=out).run()
    return out.getvalue().splitlines()
