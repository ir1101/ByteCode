"""Recursive descent parser: turns a token list into an AST.

Grammar (lowest to highest precedence for expressions):

    program     := (funcdef | statement)* EOF
    funcdef     := "func" IDENT "(" params? ")" block      (top level only)
    params      := IDENT ("," IDENT)*
    statement   := assign | print | if | while | for | block
                 | call ";" | "return" expr? ";" | "break" ";" | "continue" ";"
    assign      := assignment ";"
    assignment  := IDENT "=" expr
    print       := "print" expr ";"
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
    term        := unary (("*"|"/") unary)*
    unary       := "-" unary | primary
    primary     := INT | call | IDENT | "(" expr ")"
    call        := IDENT "(" (expr ("," expr)*)? ")"
"""

from ast_nodes import (Assign, BinOp, Block, Break, Call, Continue, ExprStmt,
                       For, FuncDef, If, LogicalOp, Number, Print, Program,
                       Return, UnaryOp, Var, While)
from errors import ParseError
from lexer import EOF, IDENT, INT, KEYWORD, OP

COMPARISON_OPS = {"==", "!=", "<", ">", "<=", ">="}


def describe(tok):
    return "end of file" if tok.type == EOF else repr(tok.value)


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

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
            raise ParseError(f"expected {wanted}, found {describe(got)}", line)
        return tok

    # ----- statements -----
    def parse_program(self):
        line = self.current().line
        statements = []
        while not self.check(EOF):
            if self.check(KEYWORD, "func"):
                statements.append(self.func_def())
            else:
                statements.append(self.statement())
        return Program(statements, line=line)

    def statement(self):
        if self.check(KEYWORD, "print"):
            return self.print_stmt()
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
        self.expect(OP, "=", "'=' after variable name")
        return Assign(name.value, self.expr(), line=name.line)

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
        brace = self.expect(OP, "{", "'{'")
        statements = []
        while not self.check(OP, "}"):
            if self.check(EOF):
                raise ParseError("unclosed '{' (missing '}')", brace.line)
            statements.append(self.statement())
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
        while self.check(OP, "*") or self.check(OP, "/"):
            tok = self.match(OP)
            left = BinOp(tok.value, left, self.unary(), line=tok.line)
        return left

    def unary(self):
        if (tok := self.match(OP, "-")):
            return UnaryOp("-", self.unary(), line=tok.line)
        return self.primary()

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
