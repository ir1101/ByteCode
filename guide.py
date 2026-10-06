"""The language guide: lessons that teach MiniLang itself, one idea at a time.

Each lesson is a template in templates/guide/<slug>.html. Its code examples are
written with the `example` macro (templates/guide/_macros.html), which runs them
through the real compiler when the page is rendered, so the output a lesson shows
is always the output MiniLang actually produces. On the page every example is
editable and can be run again, or opened in the playground.
"""

from dataclasses import dataclass
from functools import lru_cache

from api import run_pipeline

# Examples are small; these limits keep a deliberately endless loop quick to stop.
EXAMPLE_MAX_STEPS = 100_000
EXAMPLE_MAX_OUTPUT = 200


@dataclass(frozen=True)
class Lesson:
    slug: str
    title: str
    summary: str
    level: str = None       # a game level to practise on afterwards


LESSONS = (
    Lesson("first-program", "Your first program",
           "Print numbers, end every statement with a semicolon, and leave notes in comments.", "c1"),
    Lesson("numbers", "Numbers and arithmetic",
           "Whole numbers, the five arithmetic operators, precedence and how division rounds.", "c2"),
    Lesson("variables", "Variables",
           "Give values names, change them, and use the += shorthand.", "c3"),
    Lesson("logic", "Comparisons and logic",
           "Ask questions that answer 1 or 0, and combine them with and, or and not.", "b1"),
    Lesson("if", "Making decisions",
           "Run code only when a condition holds, with if, else and else if.", "c3"),
    Lesson("while", "Repeating with while",
           "Loop while a condition stays true, and keep a running total.", "c2"),
    Lesson("for", "for loops, break and continue",
           "Count with for, skip a turn with continue, and leave early with break.", "c5"),
    Lesson("functions", "Functions",
           "Name a piece of work, give it parameters, return a result, and call it again and again.", "c6"),
    Lesson("lists", "Lists",
           "Keep many values in one variable, index them, grow them and walk through them.", "c11"),
    Lesson("input", "Reading input",
           "Read whole numbers while the program runs, and stop at a sentinel value.", "c13"),
    Lesson("errors", "Reading error messages",
           "What each kind of error means, and how to fix it from the message alone.", "b2"),
    Lesson("putting-it-together", "Putting it together",
           "A complete program that uses functions, loops and lists, and where to go next.", "c10"),
)

LESSONS_BY_SLUG = {lesson.slug: lesson for lesson in LESSONS}


def neighbours(lesson):
    """The lessons before and after this one (None at either end)."""
    i = LESSONS.index(lesson)
    return (LESSONS[i - 1] if i > 0 else None, LESSONS[i + 1] if i + 1 < len(LESSONS) else None)


@lru_cache(maxsize=256)
def _run(code, stdin):
    r = run_pipeline(code, optimize=True, stdin=stdin,
                     max_steps=EXAMPLE_MAX_STEPS, max_output_lines=EXAMPLE_MAX_OUTPUT)
    return {
        "code": code,
        "stdin": stdin,
        "lines": code.count("\n") + 1,
        "output": r["output"],
        "output_text": "\n".join(r["output"]),
        "errors": r["errors"],
        "warnings": r["warnings"],
        "ok": r["ok"],
    }


def run_example(code, stdin=""):
    """Run a lesson's example through the whole pipeline (cached: examples never change)."""
    return _run(str(code).strip("\n"), str(stdin))
