"""Web-facing API: run the whole pipeline and return every stage as JSON-ready data.

The web UI calls run_pipeline() (through app.py) and gets back tokens, AST,
bytecode, program output, an optional step-by-step trace, and a structured
error if any stage fails. Stages that finished before an error are still
returned, so the UI can show how far the program got.

lint() runs only the static stages (lexer, parser, semantic analysis, type
checking), which is fast enough for the editor to call while you type.
"""

import copy
import io

from ast_nodes import dump, to_dict
from compiler import compile_program
from errors import CompileError, LexError, MiniLangError, ParseError, SemanticError, TypeCheckError, VMError
from ir import build_ir
from lexer import tokenize
from optimizer import optimize as optimize_program
from parser import parse
from semantic import analyze
from typecheck import check_types
from vm import VM, InputReader

# Safety limits for code submitted over the network.
MAX_SOURCE_CHARS = 100_000
MAX_STEPS = 1_000_000
MAX_OUTPUT_LINES = 10_000
MAX_TRACE_STEPS = 5_000
MAX_CALL_DEPTH = 1_000
MAX_INPUT_CHARS = 100_000

STAGE_NAMES = {LexError: "lex", ParseError: "parse", SemanticError: "semantic",
               TypeCheckError: "type", CompileError: "compile", VMError: "runtime"}


def token_to_dict(tok):
    return {"type": tok.type, "value": tok.value, "line": tok.line}


def bytecode_to_list(code):
    return [{"addr": i, "op": ins.op, "arg": ins.arg, "line": ins.line, "label": ins.label}
            for i, ins in enumerate(code)]


def error_to_dict(err):
    return {"stage": STAGE_NAMES.get(type(err), "error"), "message": err.message, "line": err.line}


def run_pipeline(source, optimize=True, trace=False, max_steps=MAX_STEPS,
                 max_output_lines=MAX_OUTPUT_LINES, max_trace_steps=MAX_TRACE_STEPS,
                 max_call_depth=MAX_CALL_DEPTH, inputs=None, stdin=""):
    """Run source through every stage and return a dict describing each one.

    inputs: optional {name: value} of global variables that exist before the
    program starts (how game levels pass test data in).
    stdin: the text `input x;` statements read whole numbers from.

    Keys: ok, tokens, ast, ast_dump, symbols, warnings, types, ir, bytecode,
    bytecode_unoptimized, optimizer, output, input, steps, trace,
    trace_truncated, error, errors. A stage that never ran is None. `error` is
    the first error; `errors` lists every one the failing stage found (the
    lexer, parser, semantic analysis and type checker keep going after one).
    """
    result = {
        "ok": False,
        "tokens": None,
        "ast": None,
        "ast_dump": None,
        "symbols": None,
        "warnings": [],
        "types": None,
        "ir": None,
        "bytecode": None,
        "bytecode_unoptimized": None,
        "optimizer": {"enabled": optimize, "before": None, "after": None},
        "output": [],
        "input": {"values": stdin.split(), "used": 0},   # what input statements read
        "steps": 0,
        "trace": [] if trace else None,
        "trace_truncated": False,
        "error": None,
        "errors": [],
    }
    if len(source) > MAX_SOURCE_CHARS or len(stdin) > MAX_INPUT_CHARS:
        too_long = "source" if len(source) > MAX_SOURCE_CHARS else "input"
        limit = MAX_SOURCE_CHARS if too_long == "source" else MAX_INPUT_CHARS
        result["input"]["values"] = []
        _fail(result, [{"stage": "input", "line": None,
                        "message": f"{too_long} is longer than {limit} characters"}])
        return result

    out = io.StringIO()
    reader = None
    try:
        tokens = tokenize(source)
        result["tokens"] = [token_to_dict(t) for t in tokens]

        tree = parse(tokens)
        result["ast"] = to_dict(tree)
        result["ast_dump"] = dump(tree)  # the same text tree main.py --debug prints

        analysis = analyze(tree, predefined=(inputs or {}).keys())
        result["symbols"] = analysis.to_dict()
        result["warnings"] = result["symbols"]["warnings"]
        result["types"] = check_types(tree, inputs or {}).to_dict()   # numbers vs lists, inferred
        result["ir"] = build_ir(tree).to_dict()  # three-address code, CFG, constant facts

        plain = compile_program(tree)
        code = optimize_program(tree) if optimize else plain
        result["bytecode_unoptimized"] = bytecode_to_list(plain)
        result["bytecode"] = bytecode_to_list(code)
        result["optimizer"].update(before=len(plain), after=len(code))

        record = _trace_recorder(result, max_trace_steps) if trace else None

        def on_step(addr, ins, vm):
            result["steps"] += 1  # counted here so vm.py stays untouched
            if record is not None:
                record(addr, ins, vm)

        reader = InputReader.from_text(stdin)
        vm = VM(code, out=out, max_steps=max_steps, max_output_lines=max_output_lines,
                max_call_depth=max_call_depth, on_step=on_step, input=reader)
        vm.variables.update(copy.deepcopy(inputs or {}))  # a level's test lists must not be mutated
        vm.run()
        result["ok"] = True
    except MiniLangError as e:
        _fail(result, [error_to_dict(err) for err in e.errors])
    except RecursionError:
        # The parser and compiler are recursive, so absurdly deep nesting such as
        # ((((((...)))))) can exhaust Python's stack. Report it instead of crashing.
        stage = ("parse" if result["ast"] is None else "semantic" if result["symbols"] is None
                 else "type" if result["types"] is None else "compile")
        _fail(result, [_too_deep(stage)])
    finally:
        # Keep whatever was printed, even if the program failed part-way.
        result["output"] = out.getvalue().splitlines()
        if reader is not None:
            result["input"]["used"] = reader.used
    return result


def _fail(result, errors):
    result["errors"] = errors
    result["error"] = errors[0]


def _too_deep(stage):
    return {"stage": stage, "line": None, "message": "program is nested too deeply to compile"}


def lint(source, predefined=()):
    """Only the static checks: every error and warning, without generating code or running.

    predefined: the names that exist before the program starts, or {name: value}.

    Returns {"errors": [...], "warnings": [...]}, each item with stage/code, line and message.
    """
    if len(source) > MAX_SOURCE_CHARS:
        return {"errors": [{"stage": "input", "line": None,
                            "message": f"source is longer than {MAX_SOURCE_CHARS} characters"}],
                "warnings": []}
    tree = None
    try:
        tree = parse(tokenize(source))
        warnings = analyze(tree, predefined=predefined).to_dict()["warnings"]
        check_types(tree, predefined)
        return {"errors": [], "warnings": warnings}
    except MiniLangError as e:
        return {"errors": [error_to_dict(err) for err in e.errors], "warnings": []}
    except RecursionError:
        return {"errors": [_too_deep("parse" if tree is None else "semantic")], "warnings": []}


def _snapshot(value, seen=frozenset()):
    """A JSON-safe copy of a VM value. Lists are copied so that later changes
    (a[0] = 9) can't rewrite earlier steps; a list inside itself becomes "[...]"."""
    if not isinstance(value, list):
        return value
    if id(value) in seen:
        return "[...]"
    inner = seen | {id(value)}
    return [_snapshot(v, inner) for v in value]


def _snapshot_vars(variables):
    return {name: _snapshot(value) for name, value in variables.items()}


def _trace_recorder(result, limit):
    """Return an on_step hook that snapshots the VM state after each step."""
    steps = result["trace"]

    def record(addr, ins, vm):
        if len(steps) >= limit:
            result["trace_truncated"] = True
            return
        steps.append({
            "addr": addr,
            "op": ins.op,
            "arg": ins.arg,
            "line": ins.line,
            "stack": [_snapshot(v) for v in vm.stack],
            "variables": _snapshot_vars(vm.variables),  # globals
            "locals": _snapshot_vars(vm.frames[-1].locals) if vm.frames else None,
            "call_stack": [f.name for f in vm.frames],  # outermost call first
            "frames": [{"name": f.name, "locals": _snapshot_vars(f.locals)} for f in vm.frames],
            "next_pc": vm.pc,
            "lines_printed": vm.lines_printed,  # output[:lines_printed] is visible at this step
            "input_used": vm.input.used,        # input values read so far
        })
    return record
