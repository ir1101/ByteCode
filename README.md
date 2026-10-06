# MiniLang

A small compiler written in Python 3 using only the standard library, with no parser generators.
The web playground adds Flask, which is its only dependency. Source code goes through every
classic compiler stage:

```
source ─► lexer.py ─► parser.py ─► semantic.py ─► typecheck.py ─► ir.py ─────────► optimizer.py ─► compiler.py ─► vm.py
          tokens      AST          symbol tables   number / list    three-address    propagate,      bytecode       output
                                   errors and      types, certain   code, basic      fold, drop
                                   warnings        type errors      blocks, CFG,     dead stores,
                                                                    constants,       peephole +
                                                                    liveness         tail calls
```

The lexer, parser, semantic analysis and type checker **recover from errors**, so one run reports every mistake in the file, with "did you mean" hints for misspelled keywords and names.

The website has three parts: a **landing page** (`/`), the **playground** (`/play`) where every stage is on show, and a **learning section** (`/learn`) with one chapter per stage.

## Quick start

```bash
python main.py examples/demo.ml                    # run a program
python main.py examples/demo.ml --debug            # show tokens, AST, symbols, IR, bytecode, then output
python main.py examples/demo.ml --trace            # show each instruction and the stack after it
python main.py examples/optimize.ml --debug --no-opt   # compare with the optimizer switched off
python main.py program.ml --input "3 4"            # values for input statements (or type them in)
python app.py                                      # the website on http://127.0.0.1:5000 (playground at /play)
python app.py --lan                                # same, plus every device on your Wi-Fi (prints the address)
python -m unittest discover -s tests -t . -v       # run the test suite
```

The web playground needs Flask once: `python -m pip install flask`.

**Sharing on a local network.** `python app.py --lan` listens on every network interface and prints addresses like `http://172.20.10.2:5000`. Anyone on the same Wi-Fi or hotspot can open that address, as long as the server keeps running on your machine.
- **Windows firewall:** it may ask the first time; allow Python.
- **Campus Wi-Fi:** networks often block device-to-device traffic. A phone hotspot works.
- **Safety:** submitted code only runs inside the MiniLang VM, which can't touch files or the network and is limited in steps, output and call depth. Still, only use `--lan` on networks you trust.

## Website (`app.py`)

| Page | What it is |
|---|---|
| `/` | the landing page |
| `/play` | the playground; `?example=arrays.ml&tab=ir` opens, runs and shows an example, and `#levels` opens the level picker |
| `/learn` | the learning section: one chapter per stage of the compiler |
| `/learn/<chapter>` | one chapter, e.g. `/learn/parser` |

**The look.** The site is styled as a dark "desktop", inspired by matteocourquin.com: a charcoal background with a faint grid, windows with bracketed uppercase titles such as `[PIPELINE/LIST]`, pill tags, small system-monitor readouts, big blackletter display type (Grenze Gotisch), and one electric-violet accent. Labels use Space Grotesk and code uses JetBrains Mono. Green only ever means success and red an error. The shared tokens and components live in `static/theme.css`, so all three parts match.

**The landing page** is built on real data:
- A **boot screen** runs a power-on self test: it compiles and runs `print 6 * 7;` through `/run`, and each stage reports what it actually produced. It shows once per browser session; any key skips it, and **B** reboots it.
- In the middle, a **stack machine** replays the VM trace of a small factorial program from `/run`. Its operand stack is drawn as a tower, next to a window with the source, the bytecode and the program counter, the variables and the output. **Space** or the window's button pauses it, and it starts paused if the system asks for reduced motion.
- **Windows** list the pipeline (each stage links to its chapter), the team, the levels with your stars, and the learning section. On a wide screen you can drag a window by its grip or move it with the arrow keys; positions snap to the grid and are remembered, and **R** resets them. The **+** button collapses a window.
- **Readouts** show project numbers counted from the code itself (Python lines, unit tests, opcodes, levels), the compiler's status and ping, and the keyboard shortcuts: **P** playground, **L** learn, **G** levels.

Below 1100px wide the windows stack into one scrolling column.

### Playground (`/play`)

Laid out like Compiler Explorer. The code editor (CodeMirror, loaded from a CDN) is on the left, with an **Input** drawer under it for the numbers `input` statements read; it opens by itself when the code uses `input`. The right side has one tab per pipeline stage:

- **Tokens:** a table of each token's type, value and line.
- **AST:** a collapsible tree, or the same text dump that `--debug` prints.
- **Symbols:** the warnings from semantic analysis, then the symbol table with each name's **inferred type**: every global, and for each function its parameters, locals and the globals it reads, under a typed signature such as `average(xs: list) → number`. Warning lines are also marked amber in the editor.
- **IR:** the three-address code split into basic blocks, drawn as a control-flow graph. Fall-through edges run straight down, jumps on the right, and loop back-edges dashed on the left. Each block lists its **live variables** on entry and exit, and dead stores are tagged. The **Optimized** toggle shows the code after constant propagation, with the stores that dead-store elimination removes struck through.
- **Bytecode:** the numbered instructions, with clickable jump targets and a view of the code before the optimizer ran.
- **Output:** what the program printed and which input values it read, plus a step-through of execution in the style of Python Tutor. It shows the operand stack, the global frame and each call frame at every VM step.

Hovering a row in any tab highlights its source line. Errors appear in a red box in Output, every one with its line number. If the CDN can't be reached, the editor falls back to a plain text box and everything still works.

**Checking as you type.** A moment after you stop typing, the editor sends the code to `/lint`, which runs only the lexer, parser, semantic analysis and type checker. Problems get a wavy underline (red for errors, amber for warnings) and a dot in the gutter; hover either to read the message. The pill above the editor counts them, and clicking it jumps to the first. In a level, the level's inputs count as defined.

| File | Role |
|---|---|
| `app.py` | the pages above; `POST /run` with `{"source": "...", "stdin": "3 4"}` returns the JSON described below; `POST /lint` returns `{"errors": [...], "warnings": [...]}` without compiling or running |
| `learn.py` | the chapters of the learning section |
| `templates/` | `site_base.html` (header and footer for the landing and learning pages), `landing.html`, `learn.html`, `chapter.html`, `not_found.html`, `playground.html` |
| `static/theme.css` | the shared theme: colours, fonts, grid background, windows, pills, readouts |
| `static/site.css`, `static/landing.js` | the landing and learning pages; the boot screen, windows and stack machine |
| `static/style.css`, `static/app.js` | the playground's layout and rendering; the browser never compiles anything itself |
| `static/game.js` | levels, stars, XP, achievements and toasts (see [Game mode](#game-mode)) |

A browser asking for a page that doesn't exist gets a themed 404 page; API clients get JSON.

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
  "types":    {"globals": {"xs": "list", "n": "number"}, "elements": "number",
               "functions": {"f": {"params": {...}, "returns": "number", "locals": {...},
                                   "signature": "f(xs: list) -> number"}}},
  "ir":       {"procedures": [{"name": "main", "blocks": [{"id": "B0", "lines": [...], "optimized": [...],
                "succ": ["B1"], "pred": [], "reachable": true, "constants_in": {"x": 10},
                "live_in": [], "live_out": ["i"],                     // liveness (temps left out)
                "dead": [0], "optimized_dead": [0, 1]}, ...]}],       // indexes of dead stores
               "stats": {"blocks": 4, "constant_reads": 2, "dead_stores": 1, "removed_stores": 2, ...}},
  "bytecode": [{"addr": 0, "op": "PUSH", "arg": 5, "line": 1,
                "label": null}, ...],                                 // label = "fact(n)" on a function's first instruction
  "bytecode_unoptimized": [...],
  "optimizer": {"enabled": true, "before": 7, "after": 5},
  "output":   ["5"],                                                  // kept even if a runtime error happens
  "input":    {"values": ["3", "4"], "used": 1},                      // the stdin values, and how many were read
  "steps":    5,                                                      // VM instructions executed (never capped)
  "trace":    [{"addr": 0, "op": "PUSH", "arg": 5, "line": 1,
                "stack": [5], "variables": {},                        // variables = globals
                "locals": null, "call_stack": [],                     // current call's locals, names of active calls
                "frames": [],                                         // every active call: [{"name": "fact(n)", "locals": {"n": 3}}, ...]
                "next_pc": 1,
                "lines_printed": 0,                                   // output[:lines_printed] is visible at this step
                "input_used": 0}, ...],                               // input values read so far
  "trace_truncated": false,
  "error": null,  // or {"stage": "lex|parse|semantic|type|compile|runtime|input", "message": "...", "line": 3}
  "errors": []    // every error of the failing stage; error is errors[0]
}
```

Stages that finished before an error still return their data, and stages that never ran are `null`.

**Limits** (set in `api.py`):

| Limit | Value | When it's exceeded |
|---|---|---|
| Source length, input length | 100,000 characters each | error with stage `input` |
| Execution steps | 1,000,000 | runtime error (catches infinite loops) |
| Nested calls | 1,000 | runtime error (catches infinite recursion; tail calls don't count, see [Optimizer](#optimizer)) |
| Printed lines | 10,000 | runtime error |
| Trace steps recorded | 5,000 | the program keeps running; `trace_truncated` is set to `true` |
| Nesting depth | Python's recursion limit | `parse`, `semantic` or `compile` error: "nested too deeply" |

## Game mode

The playground is also a game. Open **Levels** in the top bar.

- **Challenges (C1–C13):** write a program that passes hidden tests. The levels range from "Count to n" up to recursion, fast exponentiation and primes, then two list levels, "Largest in a list" and "Sort it", and finally "Running total", which reads its numbers with `input`. On "Sort it", bubble sort earns ★ but insertion sort sets the par.
- **Bug hunts (B1–B8):** fix a broken program. B1–B7 go in pipeline order: lexer error (`&&` isn't MiniLang), parse error, semantic error, two runtime errors, then two logic bugs. "Scope trap" is about MiniLang's scoping rule, and semantic analysis warns about it. B8, "Type trouble", starts with an error from the type checker.

Levels unlock one at a time within each track. Progress, XP and badges are saved in your browser's `localStorage`. The XP pill in the top bar opens your rank, stats and achievements, and has a reset button.

**How a level is tested.** Each test feeds your program in up to three ways:
- **Sets global variables** before your first line runs, e.g. `n = 7`. They're put straight into the VM, so your line numbers never shift.
- **Supplies input** for `input` statements, e.g. `3 4 5 0`.
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
| `POST /run` with `"level"` | `{"level": "c1", "source": "..."}` | the normal `/run` result for the level's example test, plus `harness: {inputs, epilogue, stdin, label}` |
| `POST /check` | `{"level": "c1", "source": "..."}` | each test (pass/fail, expected vs actual output, error), `metrics`, `par`, `stars`, `criteria` |

## The language

```
# comments start with '#'
x = 10;                          # assignment (variables need no declaration)
x += 5;                          # shorthand for x = x + 5 (also -=, *=, /=, %=)
print x * (2 + 3) % 4;           # print one value per line; % is the remainder
input n;                         # read a whole number into n

if x > 5 and not (x == 7) {      # no parentheses needed around the condition; braces are required
    print 1;
} else if x < 0 {
    print -1;
} else {
    print 0;
}

while x > 0 { x = x - 1; }

for i = 0; i < 10; i += 1 {      # init; condition; update (each part optional)
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
- **Input:** `input n;` reads the next whole number from the program's input: values separated by spaces or new lines. In the playground they come from the Input box; on the command line from `--input "3 4"` or from the terminal (an `input>` prompt appears). Running out of input, or a value that isn't a whole number, is a runtime error.
- **Compound assignment** is syntactic sugar: the parser turns `x += e` into `x = x + e`, and `a[i] += e` into `a[i] = a[i] + e`. That means the target and index are evaluated twice, so `a[f()] += 1` calls `f` twice.
- **Checked before anything runs** (semantic errors): undefined variables and functions, wrong numbers of arguments, duplicate or built-in function names, duplicate parameters, and `return`, `break` or `continue` in the wrong place. See [Semantic analysis](#semantic-analysis) for the warnings too.
- **Type errors** that are certain are also caught before anything runs, such as `xs + 1` when `xs` is always a list. See [Type checking](#type-checking).

### Grammar (lowest to highest precedence)

```
program    := (funcdef | statement)* EOF
funcdef    := "func" IDENT "(" (IDENT ("," IDENT)*)? ")" block
statement  := assignment ";" | "print" expr ";" | "input" IDENT ";" | call ";"
            | "if" expr block ("else" (if | block))?
            | "while" expr block
            | "for" assignment? ";" expr? ";" assignment? block
            | "return" expr? ";" | "break" ";" | "continue" ";" | block
assignment := IDENT ("[" expr "]")* ("=" | "+=" | "-=" | "*=" | "/=" | "%=") expr
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
| `TAIL_CALL addr` | reuse the current frame (keeping its return address) and jump to `addr`; made by the optimizer for `return f(...)` |
| `RET` | pop the return value, drop the frame, jump back to the caller, push the value |
| `BUILD_LIST n` | pop `n` values, push a new list of them |
| `INDEX` | pop `i`, pop a list, push `list[i]` |
| `STORE_INDEX` | pop a value, pop `i`, pop a list, set `list[i]` |
| `LEN` / `APPEND` | the built-ins `len(list)` and `append(list, value)` (which pushes the new length) |
| `PRINT` | pop and print |
| `INPUT` | read the next whole number from the program's input and push it |
| `HALT` | stop |

Every instruction records the source line it came from, so runtime errors can report a line number.

**Bytecode layout:**
- Top-level code comes first, followed by `HALT`, then each function body.
- A function starts by `STORE`-ing its arguments. The last argument is stored first, because it is on top of the stack.
- Every function ends with an implicit `PUSH 0; RET`.
- Calls are compiled before the functions' addresses are known, so their targets are filled in at the end (**back-patching**), the same technique used for forward jumps.

**Frames and the stack:** the VM keeps one operand stack shared by all calls, plus a **call stack of frames**. Each frame holds its own locals and its return address. Recursion runs on this call stack, not on Python's, and it is limited to 1,000 nested calls.

## Error recovery

A compiler that stops at the first mistake makes you fix-and-rerun once per typo, so the front end keeps going and reports everything in one run:

| Stage | Strategy | Example |
|---|---|---|
| Lexer | skip the bad characters, keep lexing | `a && b` → one error for `'&&'` with the hint "MiniLang writes 'and'" |
| Parser | **phrase level:** a `;` missing at the end of a line is reported, then the parser carries on as if it were there | three lines without `;` give three errors |
| Parser | **panic mode:** after any other error, skip tokens until a statement can start again (after a `;`, or at `{`, `}` or a statement keyword) | `x = 1 +;` then `print x;` → one error, and `print x;` is still checked |
| Semantic | record the error and keep analysing; an unknown name is reported once per scope | every undefined name in the file |
| Types | check every operation after inference has finished | every certain type error in the file |

Only the first error on each line is kept, since the rest are usually knock-on effects, and the parser stops after 20. A stage that found errors stops the pipeline, so you see every lexer error, or every parse error, or every semantic error, or every type error.

**Hints.** Errors suggest what was probably meant:
- A misspelled keyword: `whiel x < 3 {` → *did you mean 'while'?* The match uses `difflib`.
- A misspelled name: `print cout;` → *did you mean 'count'?*, and `lenght(a)` → *did you mean 'len'?*
- Habits from other languages: `elif`, `def`, `let`, `true`, `&&`, `"strings"`, `size(a)`, and `if x = 1` (*use '=='*).

## Semantic analysis

`semantic.py` runs after the parser and before any code is generated. It makes two passes over the AST:

1. **Declarations.** It collects every function, so calls may come before definitions, and every variable each scope assigns. The result is a symbol table for the global scope and one for each function, holding its parameters and locals.
2. **Uses.** It walks the code in order, resolving every name against those tables. At the same time it tracks which variables are **definitely assigned** at each point. This is a must-analysis: after an `if`/`else`, only names both branches assign count, and after a loop, only names assigned before it.

**Errors** reject the program before it runs: undefined variables and functions, argument counts, duplicate or built-in names, and misplaced `return`, `break` or `continue`. All of them are reported in one run (see [Error recovery](#error-recovery)). **Warnings** let it still run:

| Warning | Example |
|---|---|
| may be unassigned | `if n > 0 { x = 1; } print x;` (on the `n <= 0` path `x` doesn't exist) |
| scope trap | `func add(v) { total = total + v; }` reads the global `total`, but the assignment creates a separate local, so the global never changes |
| unreachable | code after `return`, `break` or `continue` |
| unused | a variable assigned but never read, an unused parameter, a function never called |
| dead store | `x = 0; if c { x = 1; } else { x = 2; }`: the `0` is never read, because both branches overwrite it (found by liveness analysis in `ir.py`) |

## Type checking

`typecheck.py` runs after semantic analysis. MiniLang has no type declarations and stays dynamically typed: a variable can hold a number now and a list later. So the checker **infers** the set of types each variable may hold at each point, and rejects an operation only when its operand's type is **certain** to be wrong. Such a line would fail every time it ran, so it is reported before anything runs, along with every other type error in the file. When a value could be either type, the VM still checks it at runtime, so a correct program is never rejected.

| Rejected | Because |
|---|---|
| `xs + 1`, `xs < 3`, `-xs` | arithmetic and ordering need numbers, and `xs` is always a list |
| `if xs { … }`, `xs and 1`, `not xs` | conditions need numbers (`0` is false) |
| `n[0]`, `n[0] = 1`, `len(n)`, `append(n, 1)` | `n` is always a number, so it can't be indexed |
| `xs[ys]` | an index must be a number |

How it works:
- **A forward data-flow analysis** over the control-flow graph from `ir.py`. The lattice is sets of types: `{number}`, `{list}`, `{number, list}` (could be either) and `{}` (no value). The meet where paths join is the union, and an assignment replaces a variable's type.
- **Interprocedural.** A parameter's type is the union of the argument types at every call, a call's type is the union of what the function returns, and a global read inside a function may hold any type the program gives it. A function nobody calls could receive anything, so its parameters are `{number, list}`.
- **List elements.** Every value put into any list (a literal, `append`, `a[i] = v`) is collected into one element type, which is what `a[i]` reads.
- These all feed each other, so the whole program is analysed again and again until nothing changes; only then are the checks made.

Error messages name the culprit, even when it is an expression: `'g[0]' is a number, so it can't be indexed with [ ]`, or `'*' needs two numbers, but 'mk()' is a list`. `python main.py file.ml --debug` prints the inferred types, and the playground shows them in the Symbols tab.

## Intermediate representation and data-flow analysis

`ir.py` lowers the AST to **three-address code**: simple instructions with at most one operator, such as `t1 = n * 2`, `x = t1 + 1` and `if_false t2 goto L3`. Each function, and the top-level code (`main`), is a separate procedure.

- **Basic blocks.** A *leader* starts a block: the first instruction, every label, and every instruction after a jump or `return`. Joining each block to the blocks it can jump or fall through to gives the **control-flow graph**.
- **Constant propagation (Kildall's algorithm).** For every block it computes which variables hold a known constant on entry. That's the *meet* of its predecessors' exit states: a variable stays constant only if every incoming path agrees on its value. Blocks are revisited until nothing changes, and loops converge because a loop variable drops out of the meet at the back edge.
- **Branch pruning.** A branch whose condition is a known constant only follows its taken edge, so a dead branch doesn't spoil the facts at the join.
- **Safety.** Nothing is known when a procedure starts, so parameters, inputs and possibly-undefined variables are never assumed constant.
- **Liveness (backward).** A variable is *live* at a point if its current value may still be read on some path from there: `live_out(B)` is the union of `live_in` over B's successors, and `live_in(B) = use(B) ∪ (live_out(B) − def(B))`. A store to a variable that isn't live right after it is a **dead store**. A call in `main` counts as reading every global that some function may read.
- **Definite assignment (forward).** The variables that surely hold a value at each point, with intersection as the meet. Reading one of them can never fail with "undefined variable", which tells the optimizer that deleting such a read is safe.

Together with the type checker, these analyses show the classic combinations:

| Analysis | Direction | Meet | Question |
|---|---|---|---|
| Constant propagation | forward | agree on the value | which variable is a known constant here? |
| Definite assignment | forward | intersection (*must*) | which variables surely exist here? |
| Type inference | forward | union (*may*) | which types can this variable hold here? |
| Liveness | backward | union (*may*) | which values may still be read from here? |

Temporaries display as `t1`, `t2`, … but their internal key is `%t1`. `%` can't appear in a MiniLang name, so a user variable called `t1` never gets mixed up with them.

The results feed the optimizer. `python main.py file.ml --debug` prints the IR, with live variables for every block, and the playground's IR tab draws it.

## Optimizer

The optimizer is on by default; `--no-opt` switches it off. It never changes what a program prints or which error it raises, and the tests check this by running a list of tricky programs both ways. The one deliberate exception is tail calls (below), which let deep recursion run that would otherwise hit the call-depth limit.

1. **Constant propagation** (on the control-flow graph, from `ir.py`): every variable read that is provably the same constant on every path becomes that constant. After `x = 10; y = x * 2;`, reading `y` becomes `20`, and a later `if y > 5` turns into a constant branch.
2. **Constant folding** (on the AST): `2 * 3 + 4` becomes `10`, `not 0` becomes `1`, and `0 and x` becomes `0`. `x / 0` and `x % 0` are deliberately left alone so the error still happens at runtime.
3. **Dead-store elimination** (liveness from `ir.py`, run on the folded tree): an assignment whose value is never read is deleted. This only happens if its right-hand side can't fail and has no side effects: a constant, a list of constants, or a variable that is definitely assigned. `x = a / b`, `x = a[i]` and `x = f()` are always kept, because they might raise an error or print. The pass repeats, since removing `y = x` can make the earlier `x = [1]` dead too. Together with propagation, `x = 10; y = x * 2; print y;` becomes just `PUSH 20; PRINT; HALT`.
4. **Peephole pass** (on the bytecode), repeated until nothing changes:
   - A constant that goes straight into a conditional jump is resolved now. This removes `if 0` and `while 0`, and lets `and`/`or` conditions jump directly to the right branch.
   - A jump that lands on another `JUMP` goes straight to the final target (**jump threading**).
   - A `JUMP` to the very next instruction is removed.
   - Code that can never be reached is removed. This includes code after a `return` and functions that are never called.
   - **Tail calls:** `CALL f` followed by `RET` becomes `TAIL_CALL f`. `return f(x);` has nothing left to do after `f` returns, so `f` reuses the current frame and returns straight to our caller. A tail-recursive `sum(5000, 0)` runs in one frame; with `--no-opt` it fails with "maximum call depth of 1000 exceeded".

| Example | Unoptimized | Folding + peephole only | Full optimizer |
|---|---|---|---|
| `demo.ml` | 87 | 82 | 58 |
| `optimize.ml` | 77 | 39 | 33 |

Semantic analysis runs on the original tree before any of this, so `0 and missing()` still reports "undefined function" even though folding removes the call.

## Learning section

`/learn` has one chapter per stage of the compiler: lexing, parsing, semantic analysis, type checking, intermediate code and data flow, optimization, code generation and the stack machine. Each chapter lists its topics, the source file it walks through, and a button that opens a matching example in the playground on the right tab.

The chapters are outlines for now; **writing the lessons is the next step**. They are data in `learn.py`: give a chapter `lessons` and its page renders them in place of the outline, and its status changes from *Outline* to *Ready* on the cards and the landing page.

## Project layout

| File | Role |
|---|---|
| `lexer.py` | characters → `Token(type, value, line)`, ending with an `EOF` token; skips bad characters and reports them all |
| `ast_nodes.py` | AST node classes, `dump()` (readable tree), `to_dict()` (JSON) |
| `parser.py` | recursive descent parser, tokens → AST; phrase-level and panic-mode error recovery, keyword hints, `+=` sugar |
| `semantic.py` | symbol tables, scope checks, definite-assignment and dead-store warnings, "did you mean" hints |
| `typecheck.py` | type inference (number / list) over the control-flow graph, and certain type errors |
| `ir.py` | three-address code, basic blocks, control-flow graph, constant propagation, liveness, definite assignment |
| `optimizer.py` | constant propagation and folding, dead-store elimination, peephole optimization and tail calls |
| `compiler.py` | AST → bytecode, back-patched jumps and calls, compile-time checks; `disassemble()` |
| `vm.py` | stack VM with a call stack of frames; step, output and call-depth limits; `on_step` hook used for tracing |
| `errors.py` | `LexError`, `ParseError`, `SemanticError`, `TypeCheckError`, `CompileError`, `VMError`; each carries a line number, and `errors` lists every error its stage found |
| `main.py` | command-line driver (`--debug`, `--trace`, `--no-opt`, `--input`) |
| `api.py` | runs the whole pipeline and returns JSON-ready data; `lint()` runs only the static checks |
| `app.py` | Flask website: the landing page, playground and learning section, plus `/run`, `/check` and `/lint` |
| `learn.py` | the learning section's chapters |
| `levels.py` | game levels, the test harness and star scoring |
| `templates/`, `static/` | the pages, the shared theme and the scripts (see [Website](#website-apppy)) |
| `tests/` | 308 unit tests: every stage, error recovery and hints, semantic analysis, type checking, input, the IR and its analyses, the optimizer (including same-behaviour checks), tail calls, arrays, the API, the levels and the website |
| `examples/` | `demo.ml`, `optimize.ml`, `functions.ml` (recursion, for, break/continue), `arrays.ml` (lists, `%`, a sieve), `dataflow.ml` (liveness, dead stores, `+=`, tail calls) |
| `.github/workflows/tests.yml` | GitHub Actions: runs the test suite on every push |
| `requirements.txt` | Flask, the only dependency (for the web playground) |
