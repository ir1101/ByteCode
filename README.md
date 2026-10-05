# MiniLang

A small compiler written in Python 3 using only the standard library, with no parser generators.
The web playground adds Flask, which is its only dependency. Source code goes through every
classic compiler stage:

```
source ─► lexer.py ─► parser.py ─► semantic.py ─► ir.py ─────────► optimizer.py ─► compiler.py ─► vm.py
          tokens      AST          symbol tables   three-address    propagate +     bytecode       output
                                   errors and      code, basic      fold, then
                                   warnings        blocks, CFG,     peephole
                                                   constant facts
```

## Quick start

```bash
python main.py examples/demo.ml                    # run a program
python main.py examples/demo.ml --debug            # show tokens, AST, symbols, IR, bytecode, then output
python main.py examples/demo.ml --trace            # show each instruction and the stack after it
python main.py examples/optimize.ml --debug --no-opt   # compare with the optimizer switched off
python app.py                                      # web playground on http://127.0.0.1:5000
python app.py --lan                                # same, plus every device on your Wi-Fi (prints the address)
python -m unittest discover -s tests -t . -v       # run the test suite
```

The web playground needs Flask once: `python -m pip install flask`.

**Sharing on a local network.** `python app.py --lan` listens on every network interface and prints addresses like `http://172.20.10.2:5000`. Anyone on the same Wi-Fi or hotspot can open that address, as long as the server keeps running on your machine.
- **Windows firewall:** it may ask the first time; allow Python.
- **Campus Wi-Fi:** networks often block device-to-device traffic. A phone hotspot works.
- **Safety:** submitted code only runs inside the MiniLang VM, which can't touch files or the network and is limited in steps, output and call depth. Still, only use `--lan` on networks you trust.

## Web playground (`app.py`)

A small Flask app, laid out like Compiler Explorer. The code editor (CodeMirror, loaded from a CDN) is on the left. The right side has one tab per pipeline stage:

- **Tokens:** a table of each token's type, value and line.
- **AST:** a collapsible tree, or the same text dump that `--debug` prints.
- **Symbols:** the warnings from semantic analysis, then the symbol table: every global, and for each function its parameters, locals and the globals it reads. Warning lines are also marked amber in the editor.
- **IR:** the three-address code split into basic blocks, drawn as a control-flow graph. Fall-through edges run straight down, jumps on the right, and loop back-edges dashed on the left. Each block shows the constants known on entry, and a toggle shows the code after constant propagation.
- **Bytecode:** the numbered instructions, with clickable jump targets and a view of the code before the optimizer ran.
- **Output:** what the program printed, plus a step-through of execution in the style of Python Tutor. It shows the operand stack, the global frame and each call frame at every VM step.

Hovering a row in any tab highlights its source line. Errors appear in a red box in Output, with their line number. If the CDN can't be reached, the editor falls back to a plain text box and everything still works.

| File | Role |
|---|---|
| `app.py` | `GET /` serves the page; `POST /run` with `{"source": "..."}` returns the JSON described below |
| `templates/index.html` | the single page |
| `static/style.css`, `static/app.js` | dark theme and rendering; the browser never compiles anything itself |
| `static/game.js` | levels, stars, XP, achievements and toasts (see [Game mode](#game-mode)) |

`/run` always answers **HTTP 200** when the request itself is valid. A MiniLang error is reported inside the result as `ok: false`. A malformed request gets HTTP 400 (or 413 if it's over 1 MB) with `{"error": "..."}`.

### Response from `/run`

```jsonc
{
  "ok": true,
  "tokens":   [{"type": "IDENT", "value": "x", "line": 1}, ...],
  "ast":      {"type": "Program", "line": 1, "statements": [...]},   // as parsed, before folding
  "ast_dump": "Program  [line 1]\n  statements:\n ...",              // readable text tree
  "symbols":  {"globals": [...], "functions": [...], "warnings": [...]},  // semantic analysis
  "warnings": [{"line": 3, "code": "scope-trap", "message": "..."}],  // also in symbols
  "ir":       {"procedures": [{"name": "main", "blocks": [{"id": "B0", "lines": [...], "optimized": [...],
                "succ": ["B1"], "pred": [], "reachable": true, "constants_in": {"x": 10}}, ...]}],
               "stats": {"blocks": 4, "constant_reads": 2, ...}},
  "bytecode": [{"addr": 0, "op": "PUSH", "arg": 5, "line": 1,
                "label": null}, ...],                                 // label = "fact(n)" on a function's first instruction
  "bytecode_unoptimized": [...],
  "optimizer": {"enabled": true, "before": 7, "after": 5},
  "output":   ["5"],                                                  // kept even if a runtime error happens
  "steps":    5,                                                      // VM instructions executed (never capped)
  "trace":    [{"addr": 0, "op": "PUSH", "arg": 5, "line": 1,
                "stack": [5], "variables": {},                        // variables = globals
                "locals": null, "call_stack": [],                     // current call's locals, names of active calls
                "frames": [],                                         // every active call: [{"name": "fact(n)", "locals": {"n": 3}}, ...]
                "next_pc": 1,
                "lines_printed": 0}, ...],                            // output[:lines_printed] is visible at this step
  "trace_truncated": false,
  "error": null  // or {"stage": "lex|parse|semantic|compile|runtime|input", "message": "...", "line": 3}
}
```

Stages that finished before an error still return their data, and stages that never ran are `null`.

**Limits** (set in `api.py`):

| Limit | Value | When it's exceeded |
|---|---|---|
| Source length | 100,000 characters | error with stage `input` |
| Execution steps | 1,000,000 | runtime error (catches infinite loops) |
| Nested calls | 1,000 | runtime error (catches infinite recursion) |
| Printed lines | 10,000 | runtime error |
| Trace steps recorded | 5,000 | the program keeps running; `trace_truncated` is set to `true` |
| Nesting depth | Python's recursion limit | `parse`, `semantic` or `compile` error: "nested too deeply" |

## Game mode

The playground is also a game. Open **Levels** in the top bar.

- **Challenges (C1–C12):** write a program that passes hidden tests. The levels range from "Count to n" up to recursion, fast exponentiation and primes, and end with two list levels: "Largest in a list" and "Sort it". On "Sort it", bubble sort earns ★ but insertion sort sets the par.
- **Bug hunts (B1–B7):** fix a broken program. They go in pipeline order: lexer error (`&&` isn't MiniLang), parse error, semantic error, two runtime errors, then two logic bugs. The last one, "Scope trap", is about MiniLang's scoping rule, and semantic analysis warns about it.

Levels unlock one at a time within each track. Progress, XP and badges are saved in your browser's `localStorage`. The XP pill in the top bar opens your rank, stats and achievements, and has a reset button.

**How a level is tested.** MiniLang has no input statement, so each test does two things:
- **Sets global variables** before your first line runs, e.g. `n = 7`. They're put straight into the VM, so your line numbers never shift.
- **May append test code** after your last line, e.g. `print fact(5);`.

Every level has several tests with different inputs, so hard-coding the answer fails. **Run** tries the example test with the full trace; **Check** runs every test on the server.

**Stars** (computed on the server in `levels.py`):

| | ★ | ★★ | ★★★ |
|---|---|---|---|
| Challenge | every test passes | optimized bytecode ≤ par size | total VM steps ≤ par |
| Bug hunt | every test passes | changed lines ≤ par (the minimal fix) | total VM steps ≤ par |

Par values and expected outputs come from reference solutions that run when the server starts, and a test checks that every reference earns 3 stars. Some levels use par to teach a lesson. On C2 a loop earns ★, but Gauss's formula earns ★★★. On C7 recursive `fib` is correct and compact (★★), but only the iterative version is fast enough for ★★★.

**XP:** 50 per star, plus 25–200 per achievement. There are 8 ranks, from *Token Tinkerer* to *Compiler Wizard*.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /run` with `"level"` | `{"level": "c1", "source": "..."}` | the normal `/run` result for the level's example test, plus `harness: {inputs, epilogue, label}` |
| `POST /check` | `{"level": "c1", "source": "..."}` | each test (pass/fail, expected vs actual output, error), `metrics`, `par`, `stars`, `criteria` |

## The language

```
# comments start with '#'
x = 10;                          # assignment (variables need no declaration)
print x * (2 + 3) % 4;           # print one value per line; % is the remainder

if x > 5 and not (x == 7) {      # no parentheses needed around the condition; braces are required
    print 1;
} else if x < 0 {
    print -1;
} else {
    print 0;
}

while x > 0 { x = x - 1; }

for i = 0; i < 10; i = i + 1 {   # init; condition; update (each part optional)
    if i == 2 { continue; }      # jumps to the update step
    if i == 5 { break; }         # leaves the innermost loop
    print i;
}

func fact(n) {                   # functions are defined at the top level only
    if n <= 1 { return 1; }
    return n * fact(n - 1);      # recursion
}
print fact(5);
show(3);                         # a call can also be a statement; its result is discarded
func show(x) { print x; }        # can be called before it is defined

xs = [5, 2, 8];                  # lists: literals, indexing, nesting
xs[1] = xs[0] + 1;               # assign into a list
append(xs, 9);                   # built-ins: append(list, value) and len(list)
print len(xs);                   # 4
print xs;                        # [5, 6, 8, 9]
grid = [[1, 2], [3, 4]];
print grid[1][0];                # 3
```

- **Values:** integers and lists. Comparisons and `and`/`or`/`not` produce `1` or `0`. In a condition, any number other than `0` counts as true; a list in a condition is a runtime error.
- **Division and remainder:** `/` rounds toward zero (`-7 / 2` is `-3`), and `%` matches it (`-7 % 3` is `-1`), so `(a / b) * b + a % b == a` always holds. Dividing or taking the remainder by 0 is a runtime error.
- **Lists** are shared by reference: after `b = a`, changing `b[0]` changes `a`, and a function can change a list it's given. Indexes are checked: `a[5]` on a shorter list, or `a + 1`, is a runtime error with a line number. `==` and `!=` compare lists item by item.
- **`and` / `or`** short-circuit: the right side is not evaluated when the left side already decides the result.
- **Chained comparisons** like `1 < x < 3` are rejected. Write `1 < x and x < 3` instead.
- **Functions and scope:**
  - Parameters, and any variable assigned inside a function, are local to that call. Every call, including a recursive one, gets its own frame.
  - A function can read global variables. Assigning to a name inside a function creates a local and never changes the global.
  - A function can't see its caller's locals.
  - Falling off the end of a function, or a bare `return;`, returns `0`.
- **Checked before anything runs** (semantic errors): undefined variables and functions, wrong numbers of arguments, duplicate or built-in function names, duplicate parameters, and `return`, `break` or `continue` in the wrong place. See [Semantic analysis](#semantic-analysis) for the warnings too.

### Grammar (lowest to highest precedence)

```
program    := (funcdef | statement)* EOF
funcdef    := "func" IDENT "(" (IDENT ("," IDENT)*)? ")" block
statement  := assignment ";" | "print" expr ";" | call ";"
            | "if" expr block ("else" (if | block))?
            | "while" expr block
            | "for" assignment? ";" expr? ";" assignment? block
            | "return" expr? ";" | "break" ";" | "continue" ";" | block
assignment := IDENT ("[" expr "]")* "=" expr
block      := "{" statement* "}"
expr       := and_expr ("or" and_expr)*
and_expr   := not_expr ("and" not_expr)*
not_expr   := "not" not_expr | comparison
comparison := additive (("=="|"!="|"<"|">"|"<="|">=") additive)?
additive   := term (("+"|"-") term)*
term       := unary (("*"|"/"|"%") unary)*
unary      := "-" unary | postfix
postfix    := primary ("[" expr "]")*
primary    := INT | call | IDENT | "(" expr ")" | "[" (expr ("," expr)*)? "]"
call       := IDENT "(" (expr ("," expr)*)? ")"            # len() and append() are built in
```

## Bytecode (stack machine)

| Instruction | Effect |
|---|---|
| `PUSH n` | push the constant `n` |
| `LOAD name` | push a variable: the current call's locals first, then globals |
| `STORE name` | pop into a variable: the current call's locals, or globals at top level |
| `POP` | discard the top value (the result of a call used as a statement) |
| `ADD SUB MUL DIV MOD` | pop `b`, pop `a`, push `a op b` |
| `EQ NE LT GT LE GE` | pop `b`, pop `a`, push `1` or `0` |
| `NEG` / `NOT` | negate the top value / replace it with `1` if it is `0`, else `0` |
| `JUMP addr` | jump to `addr` |
| `JUMP_IF_FALSE addr` | pop; jump to `addr` if the value was `0` |
| `CALL addr` | push a new frame that remembers the return address, then jump to `addr` |
| `RET` | pop the return value, drop the frame, jump back to the caller, push the value |
| `BUILD_LIST n` | pop `n` values, push a new list of them |
| `INDEX` | pop `i`, pop a list, push `list[i]` |
| `STORE_INDEX` | pop a value, pop `i`, pop a list, set `list[i]` |
| `LEN` / `APPEND` | the built-ins `len(list)` and `append(list, value)` (which pushes the new length) |
| `PRINT` | pop and print |
| `HALT` | stop |

Every instruction records the source line it came from, so runtime errors can report a line number.

**Bytecode layout:**
- Top-level code comes first, followed by `HALT`, then each function body.
- A function starts by `STORE`-ing its arguments. The last argument is stored first, because it is on top of the stack.
- Every function ends with an implicit `PUSH 0; RET`.
- Calls are compiled before the functions' addresses are known, so their targets are filled in at the end (**back-patching**), the same technique used for forward jumps.

**Frames and the stack:** the VM keeps one operand stack shared by all calls, plus a **call stack of frames**. Each frame holds its own locals and its return address. Recursion runs on this call stack, not on Python's, and it is limited to 1,000 nested calls.

## Semantic analysis

`semantic.py` runs after the parser and before any code is generated. It makes two passes over the AST:

1. **Declarations.** It collects every function, so calls may come before definitions, and every variable each scope assigns. The result is a symbol table for the global scope and one for each function, holding its parameters and locals.
2. **Uses.** It walks the code in order, resolving every name against those tables. At the same time it tracks which variables are **definitely assigned** at each point. This is a must-analysis: after an `if`/`else`, only names both branches assign count, and after a loop, only names assigned before it.

**Errors** reject the program before it runs: undefined variables and functions, argument counts, duplicate or built-in names, and misplaced `return`, `break` or `continue`. **Warnings** let it still run:

| Warning | Example |
|---|---|
| may be unassigned | `if n > 0 { x = 1; } print x;` (on the `n <= 0` path `x` doesn't exist) |
| scope trap | `func add(v) { total = total + v; }` reads the global `total`, but the assignment creates a separate local, so the global never changes |
| unreachable | code after `return`, `break` or `continue` |
| unused | a variable assigned but never read, an unused parameter, a function never called |

## Intermediate representation and constant propagation

`ir.py` lowers the AST to **three-address code**: simple instructions with at most one operator, such as `t1 = n * 2`, `x = t1 + 1` and `if_false t2 goto L3`. Each function, and the top-level code (`main`), is a separate procedure.

- **Basic blocks.** A *leader* starts a block: the first instruction, every label, and every instruction after a jump or `return`. Joining each block to the blocks it can jump or fall through to gives the **control-flow graph**.
- **Constant propagation (Kildall's algorithm).** For every block it computes which variables hold a known constant on entry. That's the *meet* of its predecessors' exit states: a variable stays constant only if every incoming path agrees on its value. Blocks are revisited until nothing changes, and loops converge because a loop variable drops out of the meet at the back edge.
- **Branch pruning.** A branch whose condition is a known constant only follows its taken edge, so a dead branch doesn't spoil the facts at the join.
- **Safety.** Nothing is known when a procedure starts, so parameters, inputs and possibly-undefined variables are never assumed constant.

The results feed the optimizer. `python main.py file.ml --debug` prints the IR, and the playground's IR tab draws it.

## Optimizer

The optimizer is on by default; `--no-opt` switches it off. It never changes what a program prints or which error it raises, and the tests check this by running a list of tricky programs both ways.

1. **Constant propagation** (on the control-flow graph, from `ir.py`): every variable read that is provably the same constant on every path becomes that constant. After `x = 10; y = x * 2;`, reading `y` becomes `20`, and a later `if y > 5` turns into a constant branch. This takes `demo.ml` from 82 to 62 instructions.
2. **Constant folding** (on the AST): `2 * 3 + 4` becomes `10`, `not 0` becomes `1`, and `0 and x` becomes `0`. `x / 0` and `x % 0` are deliberately left alone so the error still happens at runtime.
3. **Peephole pass** (on the bytecode), repeated until nothing changes:
   - A constant that goes straight into a conditional jump is resolved now. This removes `if 0` and `while 0`, and lets `and`/`or` conditions jump directly to the right branch.
   - A jump that lands on another `JUMP` goes straight to the final target (**jump threading**).
   - A `JUMP` to the very next instruction is removed.
   - Code that can never be reached is removed. This includes code after a `return` and functions that are never called.

Semantic analysis runs on the original tree before any of this, so `0 and missing()` still reports "undefined function" even though folding removes the call.

## Project layout

| File | Role |
|---|---|
| `lexer.py` | characters → `Token(type, value, line)`, ending with an `EOF` token |
| `ast_nodes.py` | AST node classes, `dump()` (readable tree), `to_dict()` (JSON) |
| `parser.py` | recursive descent parser, tokens → AST |
| `semantic.py` | symbol tables, scope checks, definite-assignment warnings |
| `ir.py` | three-address code, basic blocks, control-flow graph, constant propagation |
| `optimizer.py` | propagation-driven constant folding and peephole optimization |
| `compiler.py` | AST → bytecode, back-patched jumps and calls, compile-time checks; `disassemble()` |
| `vm.py` | stack VM with a call stack of frames; step, output and call-depth limits; `on_step` hook used for tracing |
| `errors.py` | `LexError`, `ParseError`, `SemanticError`, `CompileError`, `VMError`; each carries a line number |
| `main.py` | command-line driver (`--debug`, `--trace`, `--no-opt`) |
| `api.py` | runs the whole pipeline and returns JSON-ready data |
| `app.py` | Flask web playground: serves the page, `/run` and `/check` |
| `levels.py` | game levels, the test harness and star scoring |
| `templates/`, `static/` | the playground's page, stylesheet and scripts (`app.js` for the pipeline view, `game.js` for the game) |
| `tests/` | 202 unit tests: every stage, semantic analysis, the IR, the optimizer (including same-behaviour checks), arrays, the API, the levels and the Flask app |
| `examples/` | `demo.ml`, `optimize.ml`, `functions.ml` (recursion, for, break/continue), `arrays.ml` (lists, `%`, a sieve) |
| `.github/workflows/tests.yml` | GitHub Actions: runs the test suite on every push |
| `requirements.txt` | Flask, the only dependency (for the web playground) |
