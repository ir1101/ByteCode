"""Game levels for the MiniLang playground: challenges and bug hunts.

MiniLang has no input statement, so a test feeds a program in two ways:
  * inputs   - global variables that already exist when the program starts
               (e.g. n = 7), set directly in the VM, so the player's source
               and its line numbers are untouched;
  * epilogue - test code appended after the player's last line, e.g.
               `print fact(5);` for levels where you write a function.

Every level has several tests with different inputs, so hard-coding the
answer fails. Expected outputs and the "par" scores behind the stars are
computed by running the reference solutions when this module is imported.
"""

import difflib
from dataclasses import dataclass, field

from api import run_pipeline

CHECK_MAX_STEPS = 200_000        # per test; generous for every reference solution
CHECK_MAX_OUTPUT_LINES = 1_000


@dataclass(frozen=True)
class Test:
    inputs: dict = field(default_factory=dict)
    epilogue: str = ""

    def label(self):
        parts = [f"{name} = {value}" for name, value in self.inputs.items()]
        if self.epilogue:
            parts.append(self.epilogue)
        return ", ".join(parts)


@dataclass
class Level:
    id: str
    track: str            # "challenge" or "bug"
    title: str
    brief: str
    starter: str
    references: tuple     # one or more correct solutions; par is the most lenient
    tests: list
    hint: str
    bug_stage: str = None     # bug hunts: where the starter fails (lex/parse/compile/runtime/logic)
    par_changes: int = None   # bug hunts: most changed lines that still earns the 2nd star
    # Filled in by _prepare():
    expected: list = None
    par_size: int = None
    par_steps: int = None

    @property
    def code(self):
        return self.id.upper()


# --------------------------------------------------------------------------- #
#  Running a program against a test
# --------------------------------------------------------------------------- #

def _user_line_count(source):
    return len(source.rstrip("\n").split("\n"))


def _program(source, test):
    """The player's code with the test's epilogue appended after its last line."""
    if not test.epilogue:
        return source
    return source.rstrip("\n") + "\n" + test.epilogue + "\n"


def run_test(source, test, **limits):
    result = run_pipeline(_program(source, test), optimize=True, inputs=test.inputs, **limits)
    _flag_test_code_error(result, source, test)
    return result


def _flag_test_code_error(result, source, test):
    """Mark errors whose line is in the appended test code, not the player's code."""
    err = result.get("error")
    if not err or not err.get("line") or not test.epilogue:
        return
    if err["line"] > _user_line_count(source):
        err["in_test_code"] = True
        err["message"] += (f" (found in the test code that runs after yours: `{test.epilogue}`."
                           " Check that your code defines what the test uses, and that every"
                           " '{' in your code is closed)")


def run_example(level, source):
    """Run the player's code on the level's first (example) test, with a full trace."""
    test = level.tests[0]
    result = run_pipeline(_program(source, test), optimize=True, trace=True, inputs=test.inputs)
    _flag_test_code_error(result, source, test)
    result["harness"] = {"inputs": dict(test.inputs), "epilogue": test.epilogue, "label": test.label()}
    return result


# --------------------------------------------------------------------------- #
#  Scoring
# --------------------------------------------------------------------------- #

def _significant_lines(text):
    """Code lines with comments, indentation and blank lines stripped."""
    lines = []
    for line in text.splitlines():
        code = " ".join(line.split("#", 1)[0].split())  # MiniLang has no strings, so '#' is always a comment
        if code:
            lines.append(code)
    return lines


def changed_lines(before, after):
    """How many code lines differ between two versions (a replaced line counts once)."""
    a, b = _significant_lines(before), _significant_lines(after)
    total = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            total += max(i2 - i1, j2 - j1)
    return total


def criteria(level):
    second = (f"Change at most {level.par_changes} line{'s' if level.par_changes != 1 else ''} of the original"
              if level.track == "bug"
              else f"Bytecode of at most {level.par_size} instructions")
    return ["Pass every test", second, f"At most {level.par_steps:,} VM steps across all tests"]


def check_level(level, source):
    """Run every test and score the attempt. Returns a JSON-ready dict."""
    tests = []
    size = None
    steps = 0
    for i, test in enumerate(level.tests):
        r = run_test(source, test, max_steps=CHECK_MAX_STEPS, max_output_lines=CHECK_MAX_OUTPUT_LINES)
        if i == 0 and r["bytecode"] is not None:
            size = len(r["bytecode"])
        steps += r["steps"]
        passed = r["ok"] and r["output"] == level.expected[i]
        tests.append({"label": test.label(), "inputs": dict(test.inputs), "epilogue": test.epilogue,
                      "passed": passed, "expected": level.expected[i], "output": r["output"],
                      "error": r["error"]})

    passed = all(t["passed"] for t in tests)
    changes = changed_lines(level.starter, source) if level.track == "bug" else None
    if level.track == "bug":
        second = passed and changes <= level.par_changes
    else:
        second = passed and size is not None and size <= level.par_size
    stars = [passed, second, passed and steps <= level.par_steps]

    return {
        "level": level.id,
        "passed": passed,
        "tests": tests,
        "metrics": {"size": size, "steps": steps, "changes": changes},
        "par": {"size": level.par_size, "steps": level.par_steps, "changes": level.par_changes},
        "stars": stars,
        "star_count": sum(stars),
        "criteria": criteria(level),
    }


def public_levels():
    """Everything the page may show. Reference solutions are deliberately left out."""
    out = []
    for level in LEVELS:
        example = level.tests[0]
        out.append({
            "id": level.id,
            "code": level.code,
            "track": level.track,
            "title": level.title,
            "brief": level.brief,
            "starter": level.starter,
            "hint": level.hint,
            "bug_stage": level.bug_stage,
            "inputs": list(example.inputs),
            "epilogue": example.epilogue,
            "example": {"label": example.label(), "inputs": dict(example.inputs),
                        "epilogue": example.epilogue, "expected": level.expected[0]},
            "tests_count": len(level.tests),
            "criteria": criteria(level),
            "par": {"size": level.par_size, "steps": level.par_steps, "changes": level.par_changes},
        })
    return out


# --------------------------------------------------------------------------- #
#  The levels
# --------------------------------------------------------------------------- #

def _inputs(name, *values):
    return [Test({name: v}) for v in values]


def _calls(template, *args):
    return [Test(epilogue=template.format(*a) if isinstance(a, tuple) else template.format(a)) for a in args]


LEVELS = [
    # ----------------------------------------------------------- challenges
    Level(
        id="c1", track="challenge", title="Count to n",
        brief="Print the numbers 1, 2, 3, … up to n, one per line. If n is 0, print nothing.",
        starter="# C1 · Count to n\n# n already holds a number. Press Run to try the example.\n# Print 1, 2, ..., n, one number per line.\n\n",
        references=("for i = 1; i <= n; i = i + 1 {\n    print i;\n}\n",
                    "i = 1;\nwhile i <= n {\n    print i;\n    i = i + 1;\n}\n"),
        tests=_inputs("n", 5, 1, 0, 12),
        hint="A for loop does it in three lines: for i = 1; i <= n; i = i + 1 { … }",
    ),
    Level(
        id="c2", track="challenge", title="Sum of 1..n",
        brief="Print one number: 1 + 2 + … + n. When n is 0, print 0.",
        starter="# C2 · Sum of 1..n\n# Print the single number 1 + 2 + ... + n.\n\n",
        references=("print n * (n + 1) / 2;\n",),
        tests=_inputs("n", 10, 1, 0, 100, 37),
        hint="A loop earns the first star. For all three, remember young Gauss: 1 + 2 + … + n = n × (n + 1) / 2.",
    ),
    Level(
        id="c3", track="challenge", title="Biggest of three",
        brief="Three numbers are waiting in a, b and c. Print the largest one.",
        starter="# C3 · Biggest of three\n# Print the largest of a, b and c.\n\n",
        references=("m = a;\nif b > m { m = b; }\nif c > m { m = c; }\nprint m;\n",),
        tests=[Test({"a": 3, "b": 7, "c": 5}), Test({"a": 9, "b": 2, "c": 4}), Test({"a": 1, "b": 2, "c": 8}),
               Test({"a": 6, "b": 6, "c": 1}), Test({"a": -4, "b": -9, "c": -2})],
        hint="Keep the biggest value seen so far in a variable, then compare it with the others one at a time.",
    ),
    Level(
        id="c4", track="challenge", title="Even countdown",
        brief="Print every even number from n down to 0, including 0. MiniLang has no % operator, "
              "but x is even exactly when x / 2 * 2 == x.",
        starter="# C4 · Even countdown\n# Print the even numbers from n down to 0.\n\n",
        references=("i = n / 2 * 2;\nwhile i >= 0 {\n    print i;\n    i = i - 2;\n}\n",),
        tests=_inputs("n", 7, 6, 0, 1, 10),
        hint="You only need to check evenness once: start at the largest even number ≤ n and step down by 2.",
    ),
    Level(
        id="c5", track="challenge", title="Numeric FizzBuzz",
        brief="Print the numbers 1 to n, but print -15 for multiples of 15, -3 for other multiples of 3, "
              "and -5 for other multiples of 5. MiniLang has no strings, so negative numbers stand in for "
              "Fizz, Buzz and FizzBuzz.",
        starter="# C5 · Numeric FizzBuzz\n# 1 to n, with -3 / -5 / -15 for multiples of 3 / 5 / 15.\n\n",
        references=("for i = 1; i <= n; i = i + 1 {\n"
                    "    if i / 15 * 15 == i {\n        print -15;\n"
                    "    } else if i / 3 * 3 == i {\n        print -3;\n"
                    "    } else if i / 5 * 5 == i {\n        print -5;\n"
                    "    } else {\n        print i;\n    }\n}\n",),
        tests=_inputs("n", 15, 5, 1, 20),
        hint="Check 15 first: every multiple of 15 is also a multiple of 3 and of 5. Use else if so only one line prints per number.",
    ),
    Level(
        id="c6", track="challenge", title="Factorial",
        brief="Write a function fact(n) that returns n! = 1 × 2 × … × n, where fact(0) is 1. "
              "The tests call your function for you.",
        starter="# C6 · Factorial\n# Write fact(n). The tests call it, e.g.  print fact(5);\n\n"
                "func fact(n) {\n    return 0;   # replace this\n}\n",
        references=("func fact(n) {\n    if n <= 1 { return 1; }\n    return n * fact(n - 1);\n}\n",
                    "func fact(n) {\n    r = 1;\n    for i = 2; i <= n; i = i + 1 { r = r * i; }\n    return r;\n}\n"),
        tests=_calls("print fact({});", 5, 0, 1, 10),
        hint="Recursion: fact(n) is n * fact(n - 1), and the chain stops when n <= 1.",
    ),
    Level(
        id="c7", track="challenge", title="Fibonacci",
        brief="Write fib(n): fib(0) = 0, fib(1) = 1, and every later number is the sum of the two before it. "
              "Recursion works, but can you make it fast?",
        starter="# C7 · Fibonacci\n# Write fib(n). The tests call it, e.g.  print fib(10);\n\n"
                "func fib(n) {\n    return 0;   # replace this\n}\n",
        references=("func fib(n) {\n    a = 0;\n    b = 1;\n    for i = 0; i < n; i = i + 1 {\n"
                    "        t = a + b;\n        a = b;\n        b = t;\n    }\n    return a;\n}\n",),
        tests=_calls("print fib({});", 10, 0, 1, 15),
        hint="fib(n - 1) + fib(n - 2) recomputes the same values again and again: fib(15) makes almost 2,000 calls. "
             "Walking forward with two variables needs only n steps.",
    ),
    Level(
        id="c8", track="challenge", title="Power up",
        brief="Write pow(b, e) that returns b to the power e, for e ≥ 0. pow(b, 0) is 1.",
        starter="# C8 · Power up\n# Write pow(b, e). The tests call it, e.g.  print pow(2, 10);\n\n"
                "func pow(b, e) {\n    return 0;   # replace this\n}\n",
        references=("func pow(b, e) {\n    if e == 0 { return 1; }\n    half = pow(b, e / 2);\n"
                    "    if e / 2 * 2 == e { return half * half; }\n    return half * half * b;\n}\n",),
        tests=_calls("print pow({}, {});", (2, 10), (3, 4), (7, 0), (-2, 5), (3, 20)),
        hint="Multiplying e times earns a star. For speed: b^e = (b^(e/2))², times one more b when e is odd.",
    ),
    Level(
        id="c9", track="challenge", title="GCD",
        brief="Write gcd(a, b), the greatest common divisor of two non-negative numbers. gcd(a, 0) is a.",
        starter="# C9 · GCD\n# Write gcd(a, b). The tests call it, e.g.  print gcd(48, 18);\n\n"
                "func gcd(a, b) {\n    return 0;   # replace this\n}\n",
        references=("func gcd(a, b) {\n    while b != 0 {\n        t = b;\n        b = a - a / b * b;\n"
                    "        a = t;\n    }\n    return a;\n}\n",
                    "func gcd(a, b) {\n    if b == 0 { return a; }\n    return gcd(b, a - a / b * b);\n}\n"),
        tests=_calls("print gcd({}, {});", (48, 18), (17, 5), (100, 75), (7, 0), (0, 9)),
        hint="Euclid: gcd(a, b) = gcd(b, a mod b), and a mod b is a - a / b * b.",
    ),
    Level(
        id="c10", track="challenge", title="Prime time",
        brief="Write is_prime(n): return 1 if n is prime, otherwise 0. 1 is not prime.",
        starter="# C10 · Prime time\n# Write is_prime(n). The tests call it, e.g.  print is_prime(97);\n\n"
                "func is_prime(n) {\n    return 0;   # replace this\n}\n",
        references=("func is_prime(n) {\n    if n < 2 { return 0; }\n"
                    "    for d = 2; d * d <= n; d = d + 1 {\n        if n / d * d == n { return 0; }\n    }\n"
                    "    return 1;\n}\n",),
        tests=[Test(epilogue="for i = 1; i <= 30; i = i + 1 { if is_prime(i) { print i; } }"),
               Test(epilogue="print is_prime(97);"), Test(epilogue="print is_prime(91);")],
        hint="You only need to try divisors d while d * d <= n, and you can return as soon as one divides n.",
    ),

    # ------------------------------------------------------------ bug hunts
    Level(
        id="b1", track="bug", title="Alien symbol", bug_stage="lex", par_changes=1,
        brief="This should print the remainder of n divided by 3, but the lexer rejects it. "
              "Fix it so the lexer, and every stage after it, is happy.",
        starter="# B1 · Alien symbol\n# Should print the remainder of n divided by 3.\n"
                "remainder = n % 3;\nprint remainder;\n",
        references=("# B1 · Alien symbol\n# Should print the remainder of n divided by 3.\n"
                    "remainder = n - n / 3 * 3;\nprint remainder;\n",),
        tests=_inputs("n", 10, 9, 5, 0, 100),
        hint="MiniLang has no %. For positive numbers, a % b is the same as a - a / b * b.",
    ),
    Level(
        id="b2", track="bug", title="Missing piece", bug_stage="parse", par_changes=1,
        brief="This should print 1 + 2 + … + n, but the parser stops. Find the missing piece.",
        starter="# B2 · Missing piece\n# Should print the sum 1 + 2 + ... + n.\n"
                "total = 0;\ni = 1;\nwhile i <= n {\n    total = total + i\n    i = i + 1;\n}\nprint total;\n",
        references=("# B2 · Missing piece\n# Should print the sum 1 + 2 + ... + n.\n"
                    "total = 0;\ni = 1;\nwhile i <= n {\n    total = total + i;\n    i = i + 1;\n}\nprint total;\n",),
        tests=_inputs("n", 4, 1, 0, 10),
        hint="The error names the line where a statement should have ended. What ends every statement in MiniLang?",
    ),
    Level(
        id="b3", track="bug", title="Break room", bug_stage="compile", par_changes=1,
        brief="first_big(n) should return the first number from 1 to n whose square is bigger than 50, "
              "or 0 if there isn't one. The compiler refuses it.",
        starter="# B3 · Break room\n# first_big(n): the first i in 1..n with i * i > 50, or 0 if none.\n"
                "func first_big(n) {\n    for i = 1; i <= n; i = i + 1 {\n        if i * i > 50 {\n"
                "            return i;\n        }\n    }\n    break;\n}\nprint first_big(n);\n",
        references=("# B3 · Break room\n# first_big(n): the first i in 1..n with i * i > 50, or 0 if none.\n"
                    "func first_big(n) {\n    for i = 1; i <= n; i = i + 1 {\n        if i * i > 50 {\n"
                    "            return i;\n        }\n    }\n    return 0;\n}\nprint first_big(n);\n",),
        tests=_inputs("n", 10, 5, 100, 8, 7),
        hint="break only works inside a loop. What should the function give back when the loop finds nothing?",
    ),
    Level(
        id="b4", track="bug", title="Ghost variable", bug_stage="runtime", par_changes=1,
        brief="This should count down from n to 1, one number per line. It compiles fine, "
              "then crashes as soon as it runs.",
        starter="# B4 · Ghost variable\n# Should print n, n - 1, ..., 1.\n"
                "while count > 0 {\n    print count;\n    count = count - 1;\n}\n",
        references=("# B4 · Ghost variable\n# Should print n, n - 1, ..., 1.\n"
                    "count = n;\nwhile count > 0 {\n    print count;\n    count = count - 1;\n}\n",),
        tests=_inputs("n", 3, 1, 0, 5),
        hint="The VM can only LOAD a variable after something has STOREd it.",
    ),
    Level(
        id="b5", track="bug", title="Divide by nothing", bug_stage="runtime", par_changes=5,
        brief="This should print the average (rounded down) of 1, 2, …, n, or 0 when n is 0. "
              "It works for most n, but the example uses n = 0.",
        starter="# B5 · Divide by nothing\n# Should print the average of 1..n (rounded down), or 0 when n is 0.\n"
                "total = 0;\nfor i = 1; i <= n; i = i + 1 {\n    total = total + i;\n}\nprint total / n;\n",
        references=("# B5 · Divide by nothing\n# Should print the average of 1..n (rounded down), or 0 when n is 0.\n"
                    "total = 0;\nfor i = 1; i <= n; i = i + 1 {\n    total = total + i;\n}\n"
                    "if n == 0 {\n    print 0;\n} else {\n    print total / n;\n}\n",),
        tests=_inputs("n", 0, 4, 1, 9, 10),
        hint="Guard the division with an if: when n is 0 there is nothing to average.",
    ),
    Level(
        id="b6", track="bug", title="Off by one", bug_stage="logic", par_changes=1,
        brief="This should print n! (1 × 2 × … × n, and 0! is 1). It runs without any error, "
              "but the answer is always 0.",
        starter="# B6 · Off by one\n# Should print n! = 1 * 2 * ... * n (and 0! is 1).\n"
                "result = 1;\nfor i = 0; i <= n; i = i + 1 {\n    result = result * i;\n}\nprint result;\n",
        references=("# B6 · Off by one\n# Should print n! = 1 * 2 * ... * n (and 0! is 1).\n"
                    "result = 1;\nfor i = 1; i <= n; i = i + 1 {\n    result = result * i;\n}\nprint result;\n",),
        tests=_inputs("n", 5, 0, 1, 6),
        hint="Step through it: what is result after the very first time round the loop?",
    ),
    Level(
        id="b7", track="bug", title="Scope trap", bug_stage="logic", par_changes=2,
        brief="This should print 1² + 2² + … + n². add() looks right, yet total stays 0. "
              "This one is about how MiniLang's scopes work.",
        starter="# B7 · Scope trap\n# Should print 1*1 + 2*2 + ... + n*n.\n"
                "total = 0;\nfunc add(x) {\n    total = total + x;\n}\n"
                "for i = 1; i <= n; i = i + 1 {\n    add(i * i);\n}\nprint total;\n",
        references=("# B7 · Scope trap\n# Should print 1*1 + 2*2 + ... + n*n.\n"
                    "total = 0;\nfunc add(x) {\n    return total + x;\n}\n"
                    "for i = 1; i <= n; i = i + 1 {\n    total = add(i * i);\n}\nprint total;\n",),
        tests=_inputs("n", 3, 1, 10, 0),
        hint="Assigning to a variable inside a function creates a new local, so the global total never changes. "
             "How else can a function hand a value back?",
    ),
]

LEVELS_BY_ID = {level.id: level for level in LEVELS}


def _prepare(level):
    """Run the references to get each test's expected output and the par scores."""
    sizes, step_totals = [], []
    for ref in level.references:
        outputs, steps, size = [], 0, None
        for i, test in enumerate(level.tests):
            r = run_test(ref, test, max_steps=CHECK_MAX_STEPS, max_output_lines=CHECK_MAX_OUTPUT_LINES)
            if not r["ok"]:
                raise RuntimeError(f"reference for level {level.id} failed: {r['error']}")
            outputs.append(r["output"])
            steps += r["steps"]
            if i == 0:
                size = len(r["bytecode"])
        if level.expected is None:
            level.expected = outputs
        elif outputs != level.expected:
            raise RuntimeError(f"references for level {level.id} disagree")
        sizes.append(size)
        step_totals.append(steps)
    level.par_size = max(sizes)
    level.par_steps = max(step_totals)


for _level in LEVELS:
    _prepare(_level)
