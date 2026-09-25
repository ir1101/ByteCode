"""Error types shared by every stage of the MiniLang pipeline."""


class MiniLangError(Exception):
    """Base class for all MiniLang errors. Carries the source line number."""

    stage = "Error"

    def __init__(self, message, line=None):
        self.message = message
        self.line = line
        where = f" at line {line}" if line is not None else ""
        super().__init__(f"{self.stage}{where}: {message}")


class LexError(MiniLangError):
    stage = "LexError"


class ParseError(MiniLangError):
    stage = "ParseError"


class CompileError(MiniLangError):
    stage = "CompileError"


class VMError(MiniLangError):
    stage = "RuntimeError"
