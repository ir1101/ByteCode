"""Web-facing API: run the whole pipeline and return every stage as JSON-ready data.

The web UI calls run_pipeline() (through app.py) and gets back tokens, AST,
bytecode, program output, an optional step-by-step trace, and a structured
error if any stage fails. Stages that finished before an error are still
returned, so the UI can show how far the program got.
"""

import io

from ast_nodes import dump, to_dict
from compiler import compile_program
from errors import CompileError, LexError, MiniLangError, ParseError, VMError
from lexer import tokenize
from optimizer import optimize as optimize_program
from parser import parse
from vm import VM

# Safety limits for code submitted over the network.
MAX_SOURCE_CHARS = 100_000
MAX_STEPS = 1_000_000
MAX_OUTPUT_LINES = 10_000
MAX_TRACE_STEPS = 5_000
MAX_CALL_DEPTH = 1_000

STAGE_NAMES = {LexError: "lex", ParseError: "parse", CompileError: "compile", VMError: "runtime"}


def token_to_dict(tok):
    return {"type": tok.type, "value": tok.value, "line": tok.line}


def bytecode_to_list(code):
    return [{"addr": i, "op": ins.op, "arg": ins.arg, "line": ins.line, "label": ins.label}
            for i, ins in enumerate(code)]


def error_to_dict(err):
    return {"stage": STAGE_NAMES.get(type(err), "error"), "message": err.message, "line": err.line}


def run_pipeline(source, optimize=True, trace=False, max_steps=MAX_STEPS,
                 max_output_lines=MAX_OUTPUT_LINES, max_trace_steps=MAX_TRACE_STEPS,
                 max_call_depth=MAX_CALL_DEPTH):
    """Run source through every stage and return a dict describing each one.

    Keys: ok, tokens, ast, ast_dump, bytecode, bytecode_unoptimized, optimizer,
    output, trace, trace_truncated, error. A stage that never ran is None.
    """
    result = {
        "ok": False,
        "tokens": None,
        "ast": None,
        "ast_dump": None,
        "bytecode": None,
        "bytecode_unoptimized": None,
        "optimizer": {"enabled": optimize, "before": None, "after": None},
        "output": [],
        "trace": [] if trace else None,
        "trace_truncated": False,
        "error": None,
    }
    if len(source) > MAX_SOURCE_CHARS:
        result["error"] = {"stage": "input", "line": None,
                           "message": f"source is longer than {MAX_SOURCE_CHARS} characters"}
        return result

    out = io.StringIO()
    try:
        tokens = tokenize(source)
        result["tokens"] = [token_to_dict(t) for t in tokens]

        tree = parse(tokens)
        result["ast"] = to_dict(tree)
        result["ast_dump"] = dump(tree)  # the same text tree main.py --debug prints

        plain = compile_program(tree)
        code = optimize_program(tree) if optimize else plain
        result["bytecode_unoptimized"] = bytecode_to_list(plain)
        result["bytecode"] = bytecode_to_list(code)
        result["optimizer"].update(before=len(plain), after=len(code))

        on_step = _trace_recorder(result, max_trace_steps) if trace else None
        VM(code, out=out, max_steps=max_steps, max_output_lines=max_output_lines,
           max_call_depth=max_call_depth, on_step=on_step).run()
        result["ok"] = True
    except MiniLangError as e:
        result["error"] = error_to_dict(e)
    except RecursionError:
        # The parser and compiler are recursive, so absurdly deep nesting such as
        # ((((((...)))))) can exhaust Python's stack. Report it instead of crashing.
        stage = "parse" if result["ast"] is None else "compile"
        result["error"] = {"stage": stage, "line": None,
                           "message": "program is nested too deeply to compile"}
    finally:
        # Keep whatever was printed, even if the program failed part-way.
        result["output"] = out.getvalue().splitlines()
    return result


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
            "stack": list(vm.stack),
            "variables": dict(vm.variables),  # globals
            "locals": dict(vm.frames[-1].locals) if vm.frames else None,
            "call_stack": [f.name for f in vm.frames],  # outermost call first
            "frames": [{"name": f.name, "locals": dict(f.locals)} for f in vm.frames],
            "next_pc": vm.pc,
            "lines_printed": vm.lines_printed,  # output[:lines_printed] is visible at this step
        })
    return record
