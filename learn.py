"""The learning section: one chapter per stage of the compiler.

Each chapter lists the topics it will teach, the source file it walks through,
and the playground example and tab that show the stage at work. The lessons
themselves are the next thing to write: a chapter with `lessons` renders them,
and one without shows its outline marked "being written".
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Topic:
    title: str
    summary: str


@dataclass(frozen=True)
class Chapter:
    slug: str
    title: str
    stage: str          # the pipeline stage, as the landing page lists it
    source: str         # the file the chapter walks through
    summary: str
    topics: tuple
    example: str        # examples/<example> opens in the playground
    tab: str            # the playground tab that shows this stage
    produces: str       # what the stage hands to the next one
    lessons: tuple = field(default=())   # written lessons; empty while the chapter is an outline

    @property
    def status(self):
        return "ready" if self.lessons else "outline"


CHAPTERS = (
    Chapter(
        slug="lexer", title="Lexing", stage="Lexer", source="lexer.py", example="demo.ml", tab="tokens", produces="Tokens",
        summary="How a stream of characters becomes a list of tokens, each with a type, a value and a line number.",
        topics=(
            Topic("Characters to tokens", "Why a compiler reads words, not letters, and what a token records."),
            Topic("Keywords and names", "Reading a whole word first, then deciding whether it is a keyword."),
            Topic("Longest match", "Why == is tried before =, and += before +."),
            Topic("Comments and line numbers", "What the lexer throws away, and what it must keep for error messages."),
            Topic("Recovering from bad characters", "Skipping what doesn't belong, reporting it, and carrying on."),
        ),
    ),
    Chapter(
        slug="parser", title="Parsing", stage="Parser", source="parser.py", example="functions.ml", tab="ast", produces="Syntax tree",
        summary="How recursive descent turns tokens into a syntax tree, one method per grammar rule.",
        topics=(
            Topic("Grammars", "Writing down what a valid program looks like, rule by rule."),
            Topic("Precedence by layering", "Why * binds tighter than +: one method per precedence level."),
            Topic("Building the tree", "AST nodes, and why every node keeps its line number."),
            Topic("Syntactic sugar", "How x += 1 is rewritten into x = x + 1 before anything else sees it."),
            Topic("Error recovery", "Phrase-level repairs for a missing ';', and panic mode for everything else."),
        ),
    ),
    Chapter(
        slug="semantic", title="Semantic analysis", stage="Semantic", source="semantic.py", example="functions.ml",
        tab="symbols", produces="Symbol table",
        summary="Checking that the names in a grammatically correct program actually make sense.",
        topics=(
            Topic("Symbol tables and scope", "Globals, parameters and locals, and MiniLang's scope rule."),
            Topic("Two passes", "Declaring every function first, so a call can come before the definition."),
            Topic("Definite assignment", "Tracking which variables surely have a value at each point."),
            Topic("Warnings", "The scope trap, unused names, unreachable code and dead stores."),
            Topic("Did you mean", "Suggesting the closest known name for a typo."),
        ),
    ),
    Chapter(
        slug="types", title="Type checking", stage="Types", source="typecheck.py", example="arrays.ml",
        tab="symbols", produces="Types",
        summary="Inferring which names hold numbers and which hold lists, and catching mix-ups before anything runs.",
        topics=(
            Topic("Static and dynamic typing", "What a type checker can promise in a language without declarations."),
            Topic("Types as sets", "The lattice {number, list}, and what 'could be either' means."),
            Topic("Inference as data flow", "Following types along every path of the control-flow graph."),
            Topic("Across functions", "Parameter types from call sites, return types from return statements."),
            Topic("Only certain errors", "Why the checker never rejects a program that could run correctly."),
        ),
    ),
    Chapter(
        slug="ir", title="Intermediate code and data flow", stage="IR", source="ir.py", example="dataflow.ml",
        tab="ir", produces="TAC + CFG",
        summary="Three-address code, basic blocks and the control-flow graph, and the analyses that run over them.",
        topics=(
            Topic("Three-address code", "Breaking expressions into steps with at most one operator each."),
            Topic("Basic blocks", "Leaders, and why straight-line code is the unit of analysis."),
            Topic("The control-flow graph", "Edges for jumps and fall-through, and loops as back edges."),
            Topic("Constant propagation", "Kildall's algorithm and the meet at join points."),
            Topic("Liveness", "A backward analysis: which values may still be read."),
        ),
    ),
    Chapter(
        slug="optimizer", title="Optimization", stage="Optimizer", source="optimizer.py", example="optimize.ml",
        tab="bytecode", produces="Smaller code",
        summary="Making the program smaller and faster without ever changing what it prints.",
        topics=(
            Topic("Constant folding", "Doing 2 * 3 at compile time, and why x / 0 is left alone."),
            Topic("Dead-store elimination", "Deleting assignments nobody reads, but only when that is safe."),
            Topic("Peephole optimization", "Constant branches, jump threading and unreachable code."),
            Topic("Tail calls", "Turning CALL + RET into a jump that reuses the current frame."),
            Topic("Proving it's safe", "Testing optimized and unoptimized runs against each other."),
        ),
    ),
    Chapter(
        slug="codegen", title="Code generation", stage="Compiler", source="compiler.py", example="demo.ml",
        tab="bytecode", produces="Bytecode",
        summary="Walking the syntax tree to emit instructions for a stack machine.",
        topics=(
            Topic("Stack code from a tree", "Post-order: operands first, then the operator."),
            Topic("Jumps and back-patching", "Emitting a jump before you know where it goes."),
            Topic("Short-circuit and/or", "Compiling logic into jumps instead of operators."),
            Topic("Functions", "Arguments on the stack, CALL and RET, and the bytecode layout."),
        ),
    ),
    Chapter(
        slug="vm", title="The stack machine", stage="VM", source="vm.py", example="functions.ml", tab="output", produces="Output",
        summary="The loop that fetches, decodes and executes each instruction, and the frames behind every call.",
        topics=(
            Topic("Fetch, decode, execute", "The whole machine is one loop and a program counter."),
            Topic("The operand stack", "Where every intermediate value lives."),
            Topic("Frames and the call stack", "How recursion works without Python's own stack."),
            Topic("Runtime errors and limits", "Line numbers, step limits and the call-depth limit."),
            Topic("Tracing", "How the step-through view records the machine after every instruction."),
        ),
    ),
)

CHAPTERS_BY_SLUG = {chapter.slug: chapter for chapter in CHAPTERS}


def neighbours(chapter):
    """The chapters before and after this one (None at either end)."""
    i = CHAPTERS.index(chapter)
    return (CHAPTERS[i - 1] if i > 0 else None, CHAPTERS[i + 1] if i + 1 < len(CHAPTERS) else None)
