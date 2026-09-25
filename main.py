"""MiniLang driver: source file -> lexer -> parser -> (optimizer) -> compiler -> VM."""

import argparse
import sys

from ast_nodes import dump
from compiler import compile_program, disassemble
from errors import MiniLangError
from lexer import tokenize
from optimizer import optimize
from parser import parse
from vm import VM, text_tracer


def section(title):
    print(f"\n===== {title} =====")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run a MiniLang (.ml) program.")
    ap.add_argument("source", help="path to a .ml source file")
    ap.add_argument("--debug", action="store_true",
                    help="print tokens, AST and bytecode before the program output")
    ap.add_argument("--trace", action="store_true",
                    help="print every executed instruction and the stack after it")
    ap.add_argument("--no-opt", action="store_true",
                    help="disable the optimizer (constant folding + peephole)")
    args = ap.parse_args(argv)

    try:
        with open(args.source, encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        print(f"error: cannot read {args.source}: {e.strerror}", file=sys.stderr)
        return 2

    try:
        tokens = tokenize(source)
        if args.debug:
            section("TOKENS")
            for tok in tokens:
                print(tok)

        tree = parse(tokens)
        if args.debug:
            section("AST")
            print(dump(tree))

        code = compile_program(tree) if args.no_opt else optimize(tree)
        if args.debug:
            section("BYTECODE")
            if args.no_opt:
                print("optimizer: off")
            else:
                print(f"optimizer: {len(compile_program(tree))} -> {len(code)} instructions")
            print(disassemble(code))
            section("TRACE + OUTPUT" if args.trace else "OUTPUT")

        VM(code, on_step=text_tracer(sys.stdout) if args.trace else None).run()
    except MiniLangError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
