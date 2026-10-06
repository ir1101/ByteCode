"""The learning section's second track: one chapter per stage of the compiler.

Each chapter is a template in templates/chapters/<slug>.html with one section per
topic listed here. Chapters teach from the real thing:

  * excerpt(path, "Lexer.read_word") pulls a function out of the actual source
    file (with the ast module) and colours it, so a quote can never go stale;
  * stage_view(code, "tokens") runs a MiniLang snippet through the pipeline up to
    one stage and formats what that stage produced, the same text the command
    line's --debug prints. On the page it can be edited and run again (POST /stage).
"""

import ast
import html
import io
import os
import re
import textwrap
from dataclasses import dataclass
from functools import lru_cache

from markupsafe import Markup

ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(ROOT, "templates", "chapters")


@dataclass(frozen=True)
class Topic:
    title: str
    summary: str


@dataclass(frozen=True)
class Chapter:
    slug: str
    title: str
    stage: str          # the pipeline stage, as the landing page lists it
    source: str         # the file the chapter walks through
    summary: str
    topics: tuple
    example: str        # examples/<example> opens in the playground
    tab: str            # the playground tab that shows this stage
    produces: str       # what the stage hands to the next one

    @property
    def written(self):
        return os.path.exists(os.path.join(TEMPLATES, f"{self.slug}.html"))

    @property
    def status(self):
        return "ready" if self.written else "outline"


CHAPTERS = (
    Chapter(
        slug="lexer", title="Lexing", stage="Lexer", source="lexer.py", example="demo.ml", tab="tokens", produces="Tokens",
        summary="How a stream of characters becomes a list of tokens, each with a type, a value and a line number.",
        topics=(
            Topic("Characters to tokens", "Why a compiler reads words, not letters, and what a token records."),
            Topic("Keywords and names", "Reading a whole word first, then deciding whether it is a keyword."),
            Topic("Longest match", "Why == is tried before =, and += before +."),
            Topic("Comments and line numbers", "What the lexer throws away, and what it must keep for error messages."),
            Topic("Recovering from bad characters", "Skipping what doesn't belong, reporting it, and carrying on."),
        ),
    ),
    Chapter(
        slug="parser", title="Parsing", stage="Parser", source="parser.py", example="functions.ml", tab="ast", produces="Syntax tree",
        summary="How recursive descent turns tokens into a syntax tree, one method per grammar rule.",
        topics=(
            Topic("Grammars", "Writing down what a valid program looks like, rule by rule."),
            Topic("Precedence by layering", "Why * binds tighter than +: one method per precedence level."),
            Topic("Building the tree", "AST nodes, and why every node keeps its line number."),
            Topic("Syntactic sugar", "How x += 1 is rewritten into x = x + 1 before anything else sees it."),
            Topic("Error recovery", "Phrase-level repairs for a missing ';', and panic mode for everything else."),
        ),
    ),
    Chapter(
        slug="semantic", title="Semantic analysis", stage="Semantic", source="semantic.py", example="functions.ml",
        tab="symbols", produces="Symbol table",
        summary="Checking that the names in a grammatically correct program actually make sense.",
        topics=(
            Topic("Symbol tables and scope", "Globals, parameters and locals, and MiniLang's scope rule."),
            Topic("Two passes", "Declaring every function first, so a call can come before the definition."),
            Topic("Definite assignment", "Tracking which variables surely have a value at each point."),
            Topic("Warnings", "The scope trap, unused names, unreachable code and dead stores."),
            Topic("Did you mean", "Suggesting the closest known name for a typo."),
        ),
    ),
    Chapter(
        slug="types", title="Type checking", stage="Types", source="typecheck.py", example="arrays.ml",
        tab="symbols", produces="Types",
        summary="Inferring which names hold numbers and which hold lists, and catching mix-ups before anything runs.",
        topics=(
            Topic("Static and dynamic typing", "What a type checker can promise in a language without declarations."),
            Topic("Types as sets", "The lattice {number, list}, and what 'could be either' means."),
            Topic("Inference as data flow", "Following types along every path of the control-flow graph."),
            Topic("Across functions", "Parameter types from call sites, return types from return statements."),
            Topic("Only certain errors", "Why the checker never rejects a program that could run correctly."),
        ),
    ),
    Chapter(
        slug="ir", title="Intermediate code and data flow", stage="IR", source="ir.py", example="dataflow.ml",
        tab="ir", produces="TAC + CFG",
        summary="Three-address code, basic blocks and the control-flow graph, and the analyses that run over them.",
        topics=(
            Topic("Three-address code", "Breaking expressions into steps with at most one operator each."),
            Topic("Basic blocks", "Leaders, and why straight-line code is the unit of analysis."),
            Topic("The control-flow graph", "Edges for jumps and fall-through, and loops as back edges."),
            Topic("Constant propagation", "Kildall's algorithm and the meet at join points."),
            Topic("Liveness", "A backward analysis: which values may still be read."),
        ),
    ),
    Chapter(
        slug="optimizer", title="Optimization", stage="Optimizer", source="optimizer.py", example="optimize.ml",
        tab="bytecode", produces="Smaller code",
        summary="Making the program smaller and faster without ever changing what it prints.",
        topics=(
            Topic("Constant folding", "Doing 2 * 3 at compile time, and why x / 0 is left alone."),
            Topic("Dead-store elimination", "Deleting assignments nobody reads, but only when that is safe."),
            Topic("Peephole optimization", "Constant branches, jump threading and unreachable code."),
            Topic("Tail calls", "Turning CALL + RET into a jump that reuses the current frame."),
            Topic("Proving it's safe", "Testing optimized and unoptimized runs against each other."),
        ),
    ),
    Chapter(
        slug="codegen", title="Code generation", stage="Compiler", source="compiler.py", example="demo.ml",
        tab="bytecode", produces="Bytecode",
        summary="Walking the syntax tree to emit instructions for a stack machine.",
        topics=(
            Topic("Stack code from a tree", "Post-order: operands first, then the operator."),
            Topic("Jumps and back-patching", "Emitting a jump before you know where it goes."),
            Topic("Short-circuit and/or", "Compiling logic into jumps instead of operators."),
            Topic("Functions", "Arguments on the stack, CALL and RET, and the bytecode layout."),
        ),
    ),
    Chapter(
        slug="vm", title="The stack machine", stage="VM", source="vm.py", example="functions.ml", tab="output", produces="Output",
        summary="The loop that fetches, decodes and executes each instruction, and the frames behind every call.",
        topics=(
            Topic("Fetch, decode, execute", "The whole machine is one loop and a program counter."),
            Topic("The operand stack", "Where every intermediate value lives."),
            Topic("Frames and the call stack", "How recursion works without Python's own stack."),
            Topic("Runtime errors and limits", "Line numbers, step limits and the call-depth limit."),
            Topic("Tracing", "How the step-through view records the machine after every instruction."),
        ),
    ),
)

CHAPTERS_BY_SLUG = {chapter.slug: chapter for chapter in CHAPTERS}


def neighbours(chapter):
    """The chapters before and after this one (None at either end)."""
    i = CHAPTERS.index(chapter)
    return (CHAPTERS[i - 1] if i > 0 else None, CHAPTERS[i + 1] if i + 1 < len(CHAPTERS) else None)


def slug(text):
    """A heading's id: "Characters to tokens" -> "characters-to-tokens"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# --------------------------------------------------------------------------- #
#  Quoting the real source
# --------------------------------------------------------------------------- #

PY_TOKENS = re.compile(r"""
    (?P<str>[rbfuRBFU]{0,2}(?:\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'))
  | (?P<com>\#[^\n]*)
  | (?P<deco>@\w+)
  | (?P<defname>(?<=\bdef\ )\w+|(?<=\bclass\ )\w+)
  | (?P<kw>\b(?:False|None|True|and|as|assert|break|class|continue|def|del|elif|else|except|finally|for|
              from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b)
  | (?P<self>\bself\b)
  | (?P<num>\b\d+(?:_\d+)*\b)
  | (?P<call>\b[A-Za-z_]\w*(?=\())
""", re.VERBOSE)


def highlight_python(code):
    """Python source as HTML, with a span around keywords, strings, comments and so on."""
    out, last = [], 0
    for m in PY_TOKENS.finditer(code):
        out.append(html.escape(code[last:m.start()]))
        out.append(f'<span class="py-{m.lastgroup}">{html.escape(m.group())}</span>')
        last = m.end()
    out.append(html.escape(code[last:]))
    return Markup("".join(out))


def _find(tree, qualname):
    nodes = tree.body
    found = None
    for part in qualname.split("."):
        found = next((n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == part), None)
        if found is None:
            return None
        nodes = found.body
    return found


@lru_cache(maxsize=None)
def excerpt(path, qualname=None, start=None, end=None):
    """Quote part of a project file.

    qualname: a function, class or method ("Lexer.read_word"); without one, the whole file.
    start / end: keep only the lines from the first one containing `start` to the next
    one containing `end` (both included), to quote part of a long function.
    Raises LookupError if anything can't be found, so a broken quote fails loudly.
    """
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        source = f.read()
    lines = source.split("\n")
    first, last = 1, len(lines)
    if qualname:
        node = _find(ast.parse(source), qualname)
        if node is None:
            raise LookupError(f"{qualname} not found in {path}")
        first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        last = node.end_lineno
    if start is not None:
        hits = [i for i in range(first, last + 1) if start in lines[i - 1]]
        if not hits:
            raise LookupError(f"{start!r} not found in {path} {qualname or ''}")
        first = hits[0]
    if end is not None:
        hits = [i for i in range(first, last + 1) if end in lines[i - 1]]
        if not hits:
            raise LookupError(f"{end!r} not found after {start!r} in {path} {qualname or ''}")
        last = hits[0]
    code = textwrap.dedent("\n".join(lines[first - 1:last])).strip("\n")
    numbers = range(first, first + code.count(chr(10)) + 1)
    return {"path": path, "qualname": qualname, "first": first, "last": last, "code": code,
            "html": highlight_python(code), "gutter": chr(10).join(map(str, numbers))}


# --------------------------------------------------------------------------- #
#  Running a snippet up to one stage
# --------------------------------------------------------------------------- #

VIEWS = {
    "tokens": "Tokens",
    "ast": "Syntax tree",
    "symbols": "Symbol table",
    "types": "Inferred types",
    "ir": "Three-address code and control-flow graph",
    "constants": "After constant propagation",
    "bytecode": "Bytecode (optimizer off)",
    "optimized": "Bytecode (optimizer on)",
    "trace": "VM trace (optimizer off)",
    "output": "Output",
}
STAGE_MAX_STEPS = 200_000
TRACE_LINES = 80


class _Output:
    """Holds what a PRINT prints until its trace line is written, then adds it underneath."""

    def __init__(self):
        self.pending = ""

    def write(self, text):
        self.pending += text

    def flush_to(self, sink):
        for line in self.pending.splitlines():
            sink.write(f"                prints  {line}\n")
        self.pending = ""


def _format_tokens(tokens):
    rows = ["line  type     value"]
    for t in tokens:
        rows.append(f"{t.line:>4}  {t.type:<8} {'(end of file)' if t.type == 'EOF' else t.value}")
    return "\n".join(rows)


def _format_constants(ir):
    out = []
    for proc in ir.to_dict()["procedures"]:
        out.append(f"procedure {proc['name']}")
        for b in proc["blocks"]:
            head = f"  {b['id']}" + (f" ({b['label']})" if b["label"] else "")
            if not b["reachable"]:
                out.append(head + "  [unreachable: removed]")
                continue
            facts = ", ".join(f"{k}={v}" for k, v in b["constants_in"].items())
            out.append(head + (f"  constants in: {facts}" if facts else ""))
            for i, line in enumerate(b["optimized"]):
                out.append(f"      {line}" + ("    <- dead store, removed" if i in b["optimized_dead"] else ""))
    return "\n".join(out)


@lru_cache(maxsize=512)
def _stage(code, view, stdin):
    from api import error_to_dict
    from ast_nodes import dump
    from compiler import compile_program, disassemble
    from errors import MiniLangError
    from ir import build_ir
    from lexer import tokenize
    from optimizer import optimize
    from parser import parse
    from semantic import analyze, format_symbols
    from typecheck import check_types
    from vm import VM, InputReader, text_tracer

    result = {"code": code, "stdin": stdin, "lines": code.count("\n") + 1, "view": view,
              "label": VIEWS[view], "text": "", "errors": [], "warnings": []}
    try:
        tokens = tokenize(code)
        if view == "tokens":
            result["text"] = _format_tokens(tokens)
            return result
        tree = parse(tokens)
        if view == "ast":
            result["text"] = dump(tree)
            return result
        analysis = analyze(tree)
        if view == "symbols":
            result["text"] = format_symbols(analysis)
            result["warnings"] = analysis.to_dict()["warnings"]
            return result
        types = check_types(tree)
        if view == "types":
            result["text"] = types.format()
            return result
        if view in ("ir", "constants"):
            ir = build_ir(tree)
            result["text"] = ir.format() if view == "ir" else _format_constants(ir)
            return result
        if view == "bytecode":
            program = compile_program(tree)
            result["text"] = f"{len(program)} instructions\n\n" + disassemble(program)
            return result
        if view == "optimized":
            plain, best = compile_program(tree), optimize(tree)
            result["text"] = f"{len(best)} instructions ({len(plain)} before optimizing)\n\n" + disassemble(best)
            return result
        buffer = io.StringIO()
        shown, hidden = [0], [0]   # trace steps after the first TRACE_LINES are counted, not kept
        if view == "trace":
            write_step = text_tracer(buffer)
            printed = _Output()

            def trace(addr, ins, vm):
                if shown[0] < TRACE_LINES:
                    shown[0] += 1
                    write_step(addr, ins, vm)
                    printed.flush_to(buffer)
                else:
                    hidden[0] += 1
                    printed.pending = ""
            vm = VM(compile_program(tree), out=printed, on_step=trace,
                    max_steps=STAGE_MAX_STEPS, input=InputReader.from_text(stdin))
        else:
            vm = VM(optimize(tree), out=buffer, max_steps=STAGE_MAX_STEPS, input=InputReader.from_text(stdin))
        try:
            vm.run()
        finally:
            lines = buffer.getvalue().rstrip("\n").split("\n") if buffer.getvalue() else []
            if hidden[0]:
                lines.append(f"... and {hidden[0]:,} more steps")
            result["text"] = "\n".join(lines)
    except MiniLangError as e:
        result["errors"] = [error_to_dict(err) for err in e.errors]
    except RecursionError:
        result["errors"] = [{"stage": "parse", "line": None, "message": "program is nested too deeply"}]
    return result


def stage_view(code, view, stdin=""):
    """Run a snippet up to the stage `view` names, and format what that stage produced."""
    if view not in VIEWS:
        raise ValueError(f"unknown view {view!r}")
    return _stage(str(code).strip("\n"), view, str(stdin))
