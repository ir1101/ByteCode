"""Recursive descent parser: turns a token list into an AST.

Grammar (lowest to highest precedence for expressions):

    program     := (funcdef | statement)* EOF
    funcdef     := "func" IDENT "(" params? ")" block      (top level only)
    params      := IDENT ("," IDENT)*
    statement   := assign | print | input | if | while | for | block
                 | call ";" | "return" expr? ";" | "break" ";" | "continue" ";"
    assign      := assignment ";"
    assignment  := IDENT ("[" expr "]")* ("=" | "+=" | "-=" | "*=" | "/=" | "%=") expr
                   (a = 1;  a[i] = 1;  a[i][j] = 1;  and x += e is short for x = x + e)
    print       := "print" expr ";"
    input       := "input" IDENT ";"                      (reads a whole number into the variable)
    if          := "if" expr block ("else" (if | block))?
    while       := "while" expr block
    for         := "for" assignment? ";" expr? ";" assignment? block
    block       := "{" statement* "}"

    expr        := or_expr
    or_expr     := and_expr ("or" and_expr)*
    and_expr    := not_expr ("and" not_expr)*
    not_expr    := "not" not_expr | comparison
    comparison  := additive (("=="|"!="|"<"|">"|"<="|">=") additive)?
    additive    := term (("+"|"-") term)*
    term        := unary (("*"|"/"|"%") unary)*
    unary       := "-" unary | postfix
    postfix     := primary ("[" expr "]")*
    primary     := INT | call | IDENT | "(" expr ")" | "[" (expr ("," expr)*)? "]"
    call        := IDENT "(" (expr ("," expr)*)? ")"      (len and append are built in)

Error recovery, so one run reports every syntax error rather than just the first:
  * Phrase level: a ';' missing at the end of a line is reported, then the
    parser carries on as if it had been there.
  * Panic mode: after any other error, tokens are skipped until a statement
    can start again (just after a ';', or at '{', '}' or a statement keyword).
    Only the first error on each line is kept, since the rest are usually
    knock-on effects of it.
Misspelled keywords get a hint: `whiel x < 3 {` -> did you mean 'while'?
"""

import copy
import difflib

from ast_nodes import (ArrayLit, Assign, BinOp, Block, Break, Call, Continue,
                       ExprStmt, For, FuncDef, If, Index, IndexAssign, Input, LogicalOp,
                       Number, Print, Program, Return, UnaryOp, Var, While)
from errors import ParseError, raise_all
from lexer import EOF, IDENT, INT, KEYWORD, OP

COMPARISON_OPS = {"==", "!=", "<", ">", "<=", ">="}
COMPOUND_OPS = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%"}
STATEMENT_KEYWORDS = {"if", "else", "while", "for", "print", "input", "return", "break", "continue", "func"}
MAX_ERRORS = 20

# Words from other languages, and what MiniLang does instead.
FOREIGN_WORDS = {
    "elif": "MiniLang writes 'else if'",
    "elseif": "MiniLang writes 'else if'",
    "elsif": "MiniLang writes 'else if'",
    "def": "MiniLang defines functions with 'func'",
    "function": "MiniLang defines functions with 'func'",
    "fn": "MiniLang defines functions with 'func'",
    "let": "MiniLang has no declarations: assign directly, as in x = 5;",
    "var": "MiniLang has no declarations: assign directly, as in x = 5;",
    "int": "MiniLang has no declarations: assign directly, as in x = 5;",
}


def describe(tok):
    return "end of file" if tok.type == EOF else repr(tok.value)


def keyword_hint(word):
    """' (did you mean 'while'?)' for a likely misspelled keyword, else ''."""
    if word in FOREIGN_WORDS:
        return f" ({FOREIGN_WORDS[word]})"
    match = difflib.get_close_matches(word, sorted(STATEMENT_KEYWORDS), n=1, cutoff=0.6)
    return f" (did you mean '{match[0]}'?)" if match else ""


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.errors = []

    # ----- token helpers -----
    def current(self):
        return self.tokens[self.pos]

    def check(self, type, value=None):
        tok = self.current()
        return tok.type == type and (value is None or tok.value == value)

    def at_call(self):
        """True if the current tokens are `name (` i.e. the start of a call."""
        nxt = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
        return self.check(IDENT) and nxt is not None and nxt.type == OP and nxt.value == "("

    def match(self, type, value=None):
        """Consume and return the current token if it matches, else None."""
        if self.check(type, value):
            tok = self.current()
            self.pos += 1
            return tok
        return None

    def expect(self, type, value=None, what=None):
        """Consume a required token or raise a ParseError with its line."""
        tok = self.match(type, value)
        if tok is None:
            got = self.current()
            wanted = what or repr(value if value is not None else type)
            # A missing ';' belongs to the end of the previous statement,
            # not to whatever line the next token happens to be on.
            line = self.tokens[self.pos - 1].line if value == ";" and self.pos > 0 else got.line
            err = ParseError(f"expected {wanted}, found {describe(got)}", line)
            if value == ";" and (got.type == EOF or got.line > line):
                self.record(err)   # phrase-level recovery: carry on as if the ';' were there
                return None
            raise err
        return tok

    # ----- error recovery -----
    def record(self, err):
        """Keep an error, unless its line already has one (then it's likely a knock-on effect)."""
        if any(e.line == err.line for e in self.errors):
            return
        self.errors.append(err)
        if len(self.errors) >= MAX_ERRORS:
            self.pos = len(self.tokens) - 1   # that's plenty: jump to EOF and stop

    def recovering(self, parse_one):
        """Parse one statement. On a syntax error, record it, skip ahead and return None."""
        start = self.pos
        try:
            return parse_one()
        except ParseError as err:
            self.record(err)
            self.synchronize(start)
            return None

    def synchronize(self, start):
        """Panic mode: skip tokens until a new statement can begin."""
        if self.pos == start and not self.check(EOF):
            self.pos += 1   # the statement couldn't even begin; drop its first token
        while not self.check(EOF):
            tok = self.current()
            if tok.type == OP and tok.value == ";":
                self.pos += 1
                return
            if tok.type == OP and tok.value in ("{", "}"):
                return
            if tok.type == KEYWORD and tok.value in STATEMENT_KEYWORDS:
                return
            self.pos += 1

    # ----- statements -----
    def parse_program(self):
        line = self.current().line
        statements = []
        while not self.check(EOF):
            stmt = self.recovering(self.top_level)
            if stmt is not None:
                statements.append(stmt)
        if self.errors:
            raise_all(self.errors)
        return Program(statements, line=line)

    def top_level(self):
        return self.func_def() if self.check(KEYWORD, "func") else self.statement()

    def statement(self):
        if self.check(KEYWORD, "print"):
            return self.print_stmt()
        if self.check(KEYWORD, "input"):
            return self.input_stmt()
        if self.check(KEYWORD, "if"):
            return self.if_stmt()
        if self.check(KEYWORD, "while"):
            return self.while_stmt()
        if self.check(KEYWORD, "for"):
            return self.for_stmt()
        if self.check(KEYWORD, "return"):
            return self.return_stmt()
        if self.check(KEYWORD, "break") or self.check(KEYWORD, "continue"):
            return self.loop_jump_stmt()
        if self.check(KEYWORD, "func"):
            raise ParseError("functions can only be defined at the top level", self.current().line)
        if self.check(KEYWORD, "else"):
            raise ParseError("'else' without an 'if' before it", self.current().line)
        if self.check(OP, "{"):
            return self.block()
        if self.at_call():
            call = self.call()
            self.expect(OP, ";", "';' after function call")
            return ExprStmt(call, line=call.line)
        if self.check(IDENT):
            return self.assign_stmt()
        tok = self.current()
        raise ParseError(f"expected a statement, found {describe(tok)}", tok.line)

    def func_def(self):
        kw = self.expect(KEYWORD, "func")
        name = self.expect(IDENT, what="function name")
        self.expect(OP, "(", "'(' after function name")
        params = []
        if not self.check(OP, ")"):
            params.append(self.expect(IDENT, what="parameter name").value)
            while self.match(OP, ","):
                params.append(self.expect(IDENT, what="parameter name").value)
        self.expect(OP, ")", "')' after parameters")
        body = self.block()
        return FuncDef(name.value, params, body, line=kw.line)

    def assignment(self):
        name = self.expect(IDENT, what="variable name")
        indexes = []
        while self.match(OP, "["):
            indexes.append(self.expr())
            self.expect(OP, "]", "']'")
        op = self.current()
        if op.type == OP and op.value in COMPOUND_OPS:
            self.pos += 1
        elif not indexes and not self.check(OP, "=") and keyword_hint(name.value):
            raise ParseError(f"unknown statement '{name.value}'{keyword_hint(name.value)}", name.line)
        else:
            self.expect(OP, "=", "'=' after variable name" if not indexes else "'=' after ']'")
        value = self.expr()

        # a[i][j] = v  stores into the list a[i] at position j.
        target = Var(name.value, line=name.line)
        for index in indexes[:-1]:
            target = Index(target, index, line=name.line)
        if op.value in COMPOUND_OPS:
            # Syntactic sugar: x += e is x = x + e, and a[i] += e is a[i] = a[i] + e.
            # The copy reads the old value; note that a[f()] += 1 calls f twice.
            old = Index(target, indexes[-1], line=name.line) if indexes else target
            value = BinOp(COMPOUND_OPS[op.value], copy.deepcopy(old), value, line=op.line)
        if not indexes:
            return Assign(name.value, value, line=name.line)
        return IndexAssign(target, indexes[-1], value, line=name.line)

    def assign_stmt(self):
        node = self.assignment()
        self.expect(OP, ";", "';' after assignment")
        return node

    def return_stmt(self):
        kw = self.expect(KEYWORD, "return")
        value = None if self.check(OP, ";") else self.expr()
        self.expect(OP, ";", "';' after return")
        return Return(value, line=kw.line)

    def loop_jump_stmt(self):
        kw = self.match(KEYWORD)  # "break" or "continue"
        self.expect(OP, ";", f"';' after {kw.value}")
        return (Break if kw.value == "break" else Continue)(line=kw.line)

    def for_stmt(self):
        kw = self.expect(KEYWORD, "for")
        init = None if self.check(OP, ";") else self.assignment()
        self.expect(OP, ";", "';' after for-loop initializer")
        condition = None if self.check(OP, ";") else self.expr()
        self.expect(OP, ";", "';' after for-loop condition")
        update = None if self.check(OP, "{") else self.assignment()
        body = self.block()
        return For(init, condition, update, body, line=kw.line)

    def print_stmt(self):
        kw = self.expect(KEYWORD, "print")
        value = self.expr()
        self.expect(OP, ";", "';' after print")
        return Print(value, line=kw.line)

    def input_stmt(self):
        kw = self.expect(KEYWORD, "input")
        name = self.expect(IDENT, what="a variable name after 'input'")
        self.expect(OP, ";", "';' after input")
        return Input(name.value, line=kw.line)

    def if_stmt(self):
        kw = self.expect(KEYWORD, "if")
        condition = self.expr()
        then_body = self.block()
        else_body = None
        if self.match(KEYWORD, "else"):
            if self.check(KEYWORD, "if"):  # else-if chain
                else_body = self.if_stmt()
            else:
                else_body = self.block()
        return If(condition, then_body, else_body, line=kw.line)

    def while_stmt(self):
        kw = self.expect(KEYWORD, "while")
        condition = self.expr()
        body = self.block()
        return While(condition, body, line=kw.line)

    def block(self):
        if self.check(OP, "="):   # if x = 1 { ... }
            raise ParseError("expected '{', found '=' (to compare two values, use '==')", self.current().line)
        brace = self.expect(OP, "{", "'{'")
        statements = []
        while not self.check(OP, "}"):
            if self.check(EOF):
                raise ParseError("unclosed '{' (missing '}')", brace.line)
            stmt = self.recovering(self.statement)
            if stmt is not None:
                statements.append(stmt)
        self.expect(OP, "}")
        return Block(statements, line=brace.line)

    # ----- expressions (one method per precedence level) -----
    def expr(self):
        return self.or_expr()

    def or_expr(self):
        left = self.and_expr()
        while (tok := self.match(KEYWORD, "or")):
            left = LogicalOp("or", left, self.and_expr(), line=tok.line)
        return left

    def and_expr(self):
        left = self.not_expr()
        while (tok := self.match(KEYWORD, "and")):
            left = LogicalOp("and", left, self.not_expr(), line=tok.line)
        return left

    def not_expr(self):
        if (tok := self.match(KEYWORD, "not")):
            return UnaryOp("not", self.not_expr(), line=tok.line)
        return self.comparison()

    def comparison(self):
        left = self.additive()
        tok = self.current()
        if tok.type == OP and tok.value in COMPARISON_OPS:
            self.pos += 1
            left = BinOp(tok.value, left, self.additive(), line=tok.line)
            nxt = self.current()
            if nxt.type == OP and nxt.value in COMPARISON_OPS:
                raise ParseError("comparisons cannot be chained; use 'and'", nxt.line)
        return left

    def additive(self):
        left = self.term()
        while self.check(OP, "+") or self.check(OP, "-"):
            tok = self.match(OP)
            left = BinOp(tok.value, left, self.term(), line=tok.line)
        return left

    def term(self):
        left = self.unary()
        while self.check(OP, "*") or self.check(OP, "/") or self.check(OP, "%"):
            tok = self.match(OP)
            left = BinOp(tok.value, left, self.unary(), line=tok.line)
        return left

    def unary(self):
        if (tok := self.match(OP, "-")):
            return UnaryOp("-", self.unary(), line=tok.line)
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while (tok := self.match(OP, "[")):
            index = self.expr()
            self.expect(OP, "]", "']'")
            node = Index(node, index, line=tok.line)
        return node

    def primary(self):
        if (tok := self.match(INT)):
            return Number(tok.value, line=tok.line)
        if self.at_call():
            return self.call()
        if (tok := self.match(IDENT)):
            return Var(tok.value, line=tok.line)
        if self.match(OP, "("):
            inner = self.expr()
            self.expect(OP, ")", "')'")
            return inner
        if (tok := self.match(OP, "[")):
            items = []
            if not self.check(OP, "]"):
                items.append(self.expr())
                while self.match(OP, ","):
                    items.append(self.expr())
            self.expect(OP, "]", "']' to close the list")
            return ArrayLit(items, line=tok.line)
        tok = self.current()
        raise ParseError(f"expected an expression, found {describe(tok)}", tok.line)

    def call(self):
        name = self.expect(IDENT)
        self.expect(OP, "(")
        args = []
        if not self.check(OP, ")"):
            args.append(self.expr())
            while self.match(OP, ","):
                args.append(self.expr())
        self.expect(OP, ")", "')' after arguments")
        return Call(name.value, args, line=name.line)


def parse(tokens):
    return Parser(tokens).parse_program()
