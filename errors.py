"""Error types shared by every stage of the MiniLang pipeline."""


class MiniLangError(Exception):
    """Base class for all MiniLang errors. Carries the source line number.

    A stage that recovers from errors (the lexer, parser and semantic analysis)
    keeps going after the first one and raises it at the end with `errors`
    holding everything it found, in source order.
    """

    stage = "Error"

    def __init__(self, message, line=None):
        self.message = message
        self.line = line
        self.errors = [self]
        where = f" at line {line}" if line is not None else ""
        super().__init__(f"{self.stage}{where}: {message}")


def raise_all(errors):
    """Raise the first of several errors, carrying all of them (sorted by line)."""
    errors = sorted(errors, key=lambda e: e.line or 0)
    first = errors[0]
    first.errors = errors
    raise first


class LexError(MiniLangError):
    stage = "LexError"


class ParseError(MiniLangError):
    stage = "ParseError"


class SemanticError(MiniLangError):
    stage = "SemanticError"


class CompileError(MiniLangError):
    stage = "CompileError"


class VMError(MiniLangError):
    stage = "RuntimeError"
