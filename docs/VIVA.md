# MiniLang: viva notes

A one-stop sheet for presenting the project: what it is, one program followed through every stage, every file in two lines, the questions examiners tend to ask, and a five-minute demo.

## The project in 30 seconds

MiniLang is a small programming language and a complete compiler for it, written from scratch in Python 3 with only the standard library and no parser generators. A program goes through every classic stage: **lexer → parser → semantic analysis → type checker → intermediate code with data-flow analysis → optimizer → code generator → stack virtual machine**. A Flask website shows every stage at work: a playground with a step-through debugger, a game of 21 levels, 12 lessons that teach the language, and 8 chapters that explain the compiler using its own source code.

| | |
|---|---|
| Python (compiler and website) | 3,968 lines |
| Unit tests | 338, run by GitHub Actions on every push |
| Bytecode instructions | 30 opcodes |
| Game | 13 challenges + 8 bug hunts, 63 stars |
| Learning section | 12 language lessons, 8 compiler chapters |
| Dependencies | Flask, for the website only |

## One program through every stage

```
x = 6 * 7;
if x > 40 {
    print x;
}
```

**1. Lexer** (`lexer.py`): characters become 16 tokens, each with a type, a value and a line. Spaces and line breaks disappear.

```
line  type     value
   1  IDENT    x
   1  OP       =
   1  INT      6
   1  OP       *
   1  INT      7
   1  OP       ;
   2  KEYWORD  if
   ...
   4  EOF      (end of file)
```

**2. Parser** (`parser.py`): recursive descent builds the syntax tree. Precedence comes from the grammar's layers, so `6 * 7` is a subtree.

```
Program
  Assign(name='x')
    BinOp(op='*')
      Number(value=6)
      Number(value=7)
  If
    condition: BinOp(op='>')  Var(x)  Number(40)
    then_body: Block
      Print  Var(x)
```

**3. Semantic analysis** (`semantic.py`): the symbol table resolves every name. `x` is a global assigned on line 1 and read on lines 2 and 3.

**4. Type checker** (`typecheck.py`): `x` is inferred to be a number, so nothing can be a type error.

**5. Intermediate code** (`ir.py`): three-address code in basic blocks, joined into a control-flow graph, with liveness on each block.

```
B0  -> B1, B2          live out: x
    x = 6 * 7
    t1 = x > 40
    if_false t1 goto L1
B1  -> B2              constants in: x=42
    print x
B2 (L1)  -> exit
```

**6. Data-flow analysis**: constant propagation proves `x` is 42 everywhere, so `x > 40` is true; after substitution nothing reads `x`, so its store is dead.

```
B0
    x = 42    <- dead store, removed
    t1 = 1    <- dead store, removed
B1  constants in: x=42
    print 42
```

**7. Code generation** (`compiler.py`): a post-order walk emits stack bytecode, with a back-patched jump for the `if`. 11 instructions:

```
0000  PUSH 6        0004  LOAD x          0008  LOAD x
0001  PUSH 7        0005  PUSH 40         0009  PRINT
0002  MUL           0006  GT              0010  HALT
0003  STORE x       0007  JUMP_IF_FALSE 10
```

**8. Optimizer** (`optimizer.py`): propagation, folding, dead-store elimination and the peephole pass leave **3 instructions**: `PUSH 42`, `PRINT`, `HALT`.

**9. Virtual machine** (`vm.py`): the fetch-decode-execute loop runs them and prints `42`.

## Every file in two lines

**Compiler**

| File | What it does |
|---|---|
| `lexer.py` | Turns characters into tokens (`INT`, `IDENT`, `KEYWORD`, `OP`, `EOF`) with one character of lookahead and longest match. Skips bad characters, reports all of them, and adds hints such as "MiniLang writes `and`". |
| `ast_nodes.py` | The syntax tree's node classes; every node keeps its source line. `dump()` prints the tree as text and `to_dict()` turns it into JSON for the website. |
| `parser.py` | A recursive descent parser, with one method per grammar rule and precedence by layering. Recovers from errors (phrase level for a missing `;`, panic mode otherwise), suggests misspelled keywords, and desugars `x += e`. |
| `semantic.py` | Builds symbol tables in two passes (declarations, then uses), so calls may come before definitions. Checks every name and call, tracks definite assignment, and warns about the scope trap, unused names, unreachable code and dead stores. |
| `typecheck.py` | Infers which names hold numbers or lists, as a data-flow analysis over the CFG that spans every function. Reports only errors that are certain, so a correct program is never rejected. |
| `ir.py` | Lowers the tree to three-address code, finds basic blocks and builds the control-flow graph. Runs constant propagation (Kildall), liveness and definite assignment over it. |
| `optimizer.py` | Constant propagation and folding, dead-store elimination, then a peephole pass: constant branches, jump threading, unreachable code and tail calls. Never changes what a program prints or which error it raises. |
| `compiler.py` | Walks the tree post-order to emit stack bytecode, back-patching jumps and calls. Lays out top-level code, `HALT`, then the functions; `disassemble()` prints the listing. |
| `vm.py` | The stack machine: a fetch-decode-execute loop with an operand stack and a call stack of frames. Enforces step, output and call-depth limits, reads `input`, and calls an `on_step` hook used for tracing. |
| `errors.py` | One error class per stage, each carrying a line number. A stage that recovers raises its first error with the whole list attached. |

**Running it**

| File | What it does |
|---|---|
| `main.py` | The command line: `--debug` prints every stage, `--trace` every VM step, `--no-opt` turns the optimizer off, and `--input` supplies values. |
| `api.py` | Runs the whole pipeline and returns every stage as JSON, plus the trace for the step-through. `lint()` runs only the static checks, for checking as you type. |
| `app.py` | The Flask website: the landing page, `/play`, `/learn`, and the JSON endpoints `/run`, `/lint`, `/check` and `/stage`. `--lan` shares it on the local network. |
| `levels.py` | The game's 21 levels, the test harness (inputs, stdin, appended test code) and star scoring. Expected output and par come from reference solutions run at start-up. |
| `guide.py` | The 12 language lessons. Their examples run through the real compiler when the page renders, so the output shown is always correct. |
| `learn.py` | The 8 compiler chapters. Quotes source straight out of the files with `ast`, and runs demo snippets up to one stage. |

**Website**

| File | What it does |
|---|---|
| `static/app.js` | Renders the playground: tokens, AST, symbols, the CFG drawn in SVG, bytecode, the step-through, live checking and the input box. The browser never compiles anything itself. |
| `static/game.js` | The game layer: level picker, stars, XP, ranks, achievements and toasts. Progress is kept in `localStorage`. |
| `static/landing.js` | The landing page: a boot screen that runs a real self-test, draggable windows, and a stack machine replaying a real trace. |
| `static/guide.js` | Makes the learning section's examples editable, with syntax colours. Re-runs them through `/run`, or `/stage` for a chapter demo. |
| `static/fx.js` | The bracket cursor, the coordinate trail and scrambling text. Only with a mouse; off with reduced motion. |
| `static/theme.css`, `site.css`, `style.css` | The shared dark "desktop" theme, the landing and learning pages, and the playground. |
| `tests/` | 338 tests: every stage, recovery, analyses, same behaviour with the optimizer on and off, levels, the website, every lesson example and every chapter demo. |

## Questions examiners ask

**Where is your semantic analysis?**
`semantic.py`, between the parser and the code generator. It builds symbol tables in two passes, rejects undefined names and wrong argument counts, and warns about likely mistakes. The playground's Symbols tab shows its tables.

**Why recursive descent and not a parser generator?**
The grammar is LL(1)-friendly: one token of lookahead (two for a call) always decides the rule. Hand-written code also makes good error messages and recovery easy, and each rule maps straight onto one method.

**How is operator precedence handled?**
Each precedence level is a grammar rule and a method (`or` → `and` → `not` → comparison → `+ -` → `* / %` → unary → postfix → primary). Each method parses its operands with the next, tighter one, and a loop in each makes the operators left-associative.

**What is a basic block? A control-flow graph?**
A basic block is a straight run of instructions entered only at the top and left only at the bottom. Leaders are the first instruction, every label, and every instruction after a jump. The CFG joins each block to the blocks that can run next; loops appear as back edges.

**Explain constant propagation.**
A forward data-flow analysis (Kildall's algorithm). Each block's entry state is the meet of its predecessors' exit states, keeping a variable only if every path agrees on its value. It iterates to a fixed point, and constant branches prune dead edges. The optimizer then replaces proven constant reads with literals.

**Explain liveness. What is a dead store?**
A backward analysis: `live_in(B) = use(B) ∪ (live_out(B) − def(B))`, where `live_out` is the union over successors. A store to a variable that isn't live right after it is dead. Semantic analysis warns about it, and the optimizer deletes it if its right-hand side can't fail.

**Forward vs backward, may vs must?**
Constant propagation and definite assignment run forward, liveness runs backward. Definite assignment is a *must* analysis (intersection at joins); liveness and type inference are *may* analyses (union).

**How do you know the optimizer is correct?**
`SameBehaviourTests` runs a list of tricky programs with the optimizer on and off, and they must print the same output, or raise the same error with the same line. Folding never touches `x / 0`, and dead stores are only removed when computing them can't fail.

**What is tail-call optimization?**
`return f(x)` leaves the caller nothing to do, so the peephole pass turns `CALL` followed by `RET` into `TAIL_CALL`, which reuses the current frame. Tail recursion then runs in constant stack space: `sum(5000, 0)` works, but fails with `--no-opt`.

**What is back-patching?**
A forward jump is emitted before its target exists, with a placeholder; its address is remembered and filled in once the target is known. MiniLang uses it for `if`, loops, `break`/`continue` and function calls.

**Why a stack machine?**
Code generation is a simple post-order walk with no register allocation, and the bytecode is compact. The Java VM and CPython work the same way.

**How does a function call work at runtime?**
The caller pushes the arguments and `CALL` pushes a frame (its locals and the return address). The callee `STORE`s its parameters, last first. `RET` pops the value, drops the frame, jumps back and pushes the value.

**Is MiniLang statically or dynamically typed?**
Dynamically: values carry types, and the VM checks every operation. The type checker adds static checking on top by inferring types as sets of {number, list}, and it reports only errors that are certain.

**How does error recovery work?**
The lexer skips bad characters. The parser inserts a missing `;` at the end of a line (phrase level), and otherwise skips to the next statement (panic mode), keeping one error per line. Semantic analysis and the type checker record errors and keep going, so one run shows every mistake.

**What is the scope trap?**
Assigning to a name inside a function makes it local. So `total = total + x` reads the global `total` (the local has no value yet) but writes a new local, and the global never changes. Semantic analysis warns about it, and bug hunt B7 is built on it.

**How is an infinite loop stopped?**
The VM counts steps and stops at a limit (1,000,000 in the playground), along with limits on printed lines and call depth, so code sent from a browser can't hang the server.

## A five-minute demo

1. **Landing page** (`python app.py`, open `http://127.0.0.1:5000`). The boot screen's self-test is a real compile and run of `print 6 * 7;`. Point at the stack machine replaying a real trace.
2. **Playground → Learn's IR chapter, "Open in playground"**, or pick `dataflow.ml`: show the Tokens, AST and Symbols tabs, then the IR tab's control-flow graph and its Optimized view.
3. **Bytecode tab**: toggle Optimized / Before optimizing, and point at `TAIL_CALL`.
4. **Output tab**: step through `functions.ml` to show frames growing in the recursion.
5. **Errors**: type `whiel x < 3 {`, then `count = 1; print cont;`, then `x = 5 && 3;`. Show the live underline and the hint each one gets before pressing Run: "did you mean 'while'", "did you mean 'count'", "MiniLang writes 'and'".
6. **Levels**: open B8 "Type trouble" and fix it for ★★★.
7. **Learn**: a lesson's runnable example, then a chapter's source quote with its demo.
8. **Tests**: `python -m unittest discover -s tests -t . -v`, all green.
