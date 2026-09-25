"""Hand-written lexer: turns MiniLang source text into a list of Tokens."""

from errors import LexError

# Token types
INT = "INT"
IDENT = "IDENT"
KEYWORD = "KEYWORD"
OP = "OP"
EOF = "EOF"

KEYWORDS = {"if", "else", "while", "for", "break", "continue", "print",
            "and", "or", "not", "func", "return"}

# Two-character operators must be tried before their one-character prefixes.
TWO_CHAR_OPS = {"==", "!=", "<=", ">="}
ONE_CHAR_OPS = set("+-*/<>=(){};,")


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
            elif ch.isdigit():
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
                raise LexError(f"unexpected character {ch!r}", self.line)

        tokens.append(Token(EOF, None, self.line))
        return tokens

    def read_number(self):
        line = self.line
        start = self.pos
        while self.peek().isdigit():
            self.advance()
        if self.peek().isalpha() or self.peek() == "_":
            raise LexError(f"invalid number literal starting {self.source[start:self.pos + 1]!r}", line)
        return Token(INT, int(self.source[start:self.pos]), line)

    def read_word(self):
        line = self.line
        start = self.pos
        while self.peek().isalnum() or self.peek() == "_":
            self.advance()
        word = self.source[start:self.pos]
        return Token(KEYWORD if word in KEYWORDS else IDENT, word, line)


def tokenize(source):
    return Lexer(source).tokenize()
