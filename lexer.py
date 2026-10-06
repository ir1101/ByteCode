"""Hand-written lexer: turns MiniLang source text into a list of Tokens.

Error recovery: a character that can't start a token is reported, skipped,
and lexing carries on, so one run lists every bad character in the file.
"""

from errors import LexError, raise_all

# Token types
INT = "INT"
IDENT = "IDENT"
KEYWORD = "KEYWORD"
OP = "OP"
EOF = "EOF"

KEYWORDS = {"if", "else", "while", "for", "break", "continue", "print",
            "and", "or", "not", "func", "return"}

# Two-character operators must be tried before their one-character prefixes.
# x += e is shorthand for x = x + e (the parser expands it).
TWO_CHAR_OPS = {"==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%="}
ONE_CHAR_OPS = set("+-*/%<>=(){}[];,")

# What a programmer coming from another language probably meant.
CHAR_HINTS = {
    "&": "MiniLang writes 'and' instead of '&&'",
    "|": "MiniLang writes 'or' instead of '||'",
    "!": "MiniLang writes 'not x', and '!=' for 'not equal'",
    '"': "MiniLang has no strings, only whole numbers and lists",
    "'": "MiniLang has no strings, only whole numbers and lists",
    ".": "MiniLang numbers are whole numbers, and a list's length is len(a)",
    ":": "MiniLang blocks use braces: if x > 1 { ... }",
}


def is_digit(ch):
    return "0" <= ch <= "9"  # ASCII only: int() can't read digits such as superscript two


def can_start_token(ch):
    return ch in " \t\r\n#_" or is_digit(ch) or ch.isalpha() or ch in ONE_CHAR_OPS


class Token:
    """A single lexical token: its type, its text/value, and its source line."""

    def __init__(self, type, value, line):
        self.type = type
        self.value = value
        self.line = line

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, line={self.line})"

    def __eq__(self, other):
        return (isinstance(other, Token) and self.type == other.type
                and self.value == other.value and self.line == other.line)


class Lexer:
    def __init__(self, source):
        self.source = source
        self.pos = 0
        self.line = 1
        self.errors = []

    def peek(self, offset=0):
        i = self.pos + offset
        return self.source[i] if i < len(self.source) else ""

    def advance(self):
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
        return ch

    def tokenize(self):
        tokens = []
        while self.pos < len(self.source):
            ch = self.peek()

            if ch in " \t\r\n":
                self.advance()
            elif ch == "#":  # comment runs to end of line
                while self.pos < len(self.source) and self.peek() != "\n":
                    self.advance()
            elif is_digit(ch):
                tokens.append(self.read_number())
            elif ch.isalpha() or ch == "_":
                tokens.append(self.read_word())
            elif ch + self.peek(1) in TWO_CHAR_OPS:
                line = self.line
                op = self.advance() + self.advance()
                tokens.append(Token(OP, op, line))
            elif ch in ONE_CHAR_OPS:
                tokens.append(Token(OP, self.advance(), self.line))
            else:
                self.skip_unexpected()

        if self.errors:
            raise_all(self.errors)
        tokens.append(Token(EOF, None, self.line))
        return tokens

    def skip_unexpected(self):
        """Report a run of characters that can't start a token (such as '&&'), then skip it."""
        start, line = self.pos, self.line
        self.advance()
        while self.pos < len(self.source) and not can_start_token(self.peek()):
            self.advance()
        bad = self.source[start:self.pos]
        hint = CHAR_HINTS.get(bad[0])
        message = f"unexpected character {bad!r}" if len(bad) == 1 else f"unexpected characters {bad!r}"
        self.errors.append(LexError(f"{message} ({hint})" if hint else message, line))

    def read_number(self):
        line = self.line
        start = self.pos
        while is_digit(self.peek()):
            self.advance()
        digits = self.source[start:self.pos]
        if self.peek().isalpha() or self.peek() == "_":
            while self.peek().isalnum() or self.peek() == "_":
                self.advance()  # skip the whole word, so lexing resumes after it
            self.errors.append(LexError(f"invalid number literal {self.source[start:self.pos]!r} "
                                        "(a name can't start with a digit)", line))
        return Token(INT, int(digits), line)

    def read_word(self):
        line = self.line
        start = self.pos
        while self.peek().isalnum() or self.peek() == "_":
            self.advance()
        word = self.source[start:self.pos]
        return Token(KEYWORD if word in KEYWORDS else IDENT, word, line)


def tokenize(source):
    return Lexer(source).tokenize()
