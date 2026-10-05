"""Three-address code, basic blocks, the control-flow graph and constant propagation."""
import unittest

from tests.helpers import ROOT, compile_source, run_source  # noqa: F401
from api import run_pipeline
from compiler import Instruction as I
from ir import build_ir
from lexer import tokenize
from parser import parse


def ir_of(source):
    return build_ir(parse(tokenize(source)))


def main_blocks(source):
    return ir_of(source).to_dict()["procedures"][0]["blocks"]


class LoweringTests(unittest.TestCase):
    def test_three_address_code(self):
        (block,) = main_blocks("x = 2 * (3 + y);\nprint x;")
        self.assertEqual(block["lines"], ["t1 = 3 + y", "x = 2 * t1", "print x"])

    def test_arrays_calls_and_builtins(self):
        src = "a = [1, 2];\na[0] = len(a);\nfunc f(v) { return v; }\nprint f(a[1]);"
        lines = [l for b in main_blocks(src) for l in b["lines"]]
        self.assertEqual(lines, ["a = [1, 2]", "t1 = len(a)", "a[0] = t1", "t2 = a[1]", "t3 = call f(t2)", "print t3"])

    def test_each_function_is_a_procedure(self):
        procs = ir_of("func f(n) { return n; }\nprint f(1);").to_dict()["procedures"]
        self.assertEqual([p["name"] for p in procs], ["main", "f(n)"])


class ControlFlowGraphTests(unittest.TestCase):
    def test_if_else_diamond(self):
        blocks = main_blocks("if n { x = 1; } else { x = 2; }\nprint x;")
        self.assertEqual([b["succ"] for b in blocks], [["B1", "B2"], ["B3"], ["B3"], []])
        self.assertEqual(blocks[3]["pred"], ["B1", "B2"])

    def test_while_loop_has_a_back_edge(self):
        blocks = main_blocks("i = 0;\nwhile i < 3 { i = i + 1; }\nprint i;")
        header = blocks[1]
        self.assertIn("B2", header["pred"])          # the loop body jumps back to the condition
        self.assertEqual(blocks[2]["succ"], ["B1"])

    def test_code_after_return_is_its_own_unreachable_block(self):
        procs = ir_of("func f() { return 1; print 2; }\nprint f();").to_dict()["procedures"]
        self.assertEqual([b["reachable"] for b in procs[1]["blocks"]], [True, False])


class ConstantPropagationTests(unittest.TestCase):
    def constants_in(self, source, block_index):
        return main_blocks(source)[block_index]["constants_in"]

    def test_straight_line_constants(self):
        self.assertEqual(ir_of("x = 10;\ny = x * 2;\nprint y;").stats()["constant_reads"], 2)

    def test_join_keeps_only_agreeing_values(self):
        same = "if n { k = 4; } else { k = 4; }\nprint k;"
        different = "if n { k = 4; } else { k = 5; }\nprint k;"
        self.assertEqual(self.constants_in(same, 3), {"k": 4})
        self.assertEqual(self.constants_in(different, 3), {})

    def test_loop_variable_is_not_constant(self):
        blocks = main_blocks("i = 0;\nwhile i < 3 { i = i + 1; }\nprint i;")
        self.assertNotIn("i", blocks[1]["constants_in"])

    def test_constant_branch_prunes_dead_path(self):
        blocks = main_blocks("x = 1;\nif x > 0 { y = 2; } else { y = 3; }\nprint y;")
        self.assertEqual([b["reachable"] for b in blocks], [True, True, False, True])
        self.assertEqual(blocks[3]["constants_in"]["y"], 2)   # the dead branch doesn't spoil y
        self.assertEqual(blocks[3]["optimized"], ["print 2"])

    def test_possibly_undefined_variable_is_never_assumed_constant(self):
        # On the n = 0 path x is undefined; the runtime error must not be optimized away.
        self.assertEqual(self.constants_in("if n { x = 5; }\nprint x;", 2), {})

    def test_functions_start_with_nothing_known(self):
        procs = ir_of("g = 7;\nfunc f(a) { b = 3; return a * b + g; }\nprint f(1);").to_dict()["procedures"]
        fn = procs[1]["blocks"][0]
        lines = fn["optimized"]
        self.assertTrue(any(l.endswith("= a * 3") for l in lines), lines)   # local constant b propagated
        self.assertTrue(any(l.endswith(" + g") for l in lines), lines)      # global g unknown inside f


class OptimizerIntegrationTests(unittest.TestCase):
    def test_propagation_enables_folding_and_branch_removal(self):
        code = compile_source("x = 10;\ny = x * 2;\nif y > 5 { print y; } else { print 0; }", optimize=True)
        self.assertEqual(code[-3:], [I("PUSH", 20), I("PRINT"), I("HALT")])
        self.assertNotIn("JUMP_IF_FALSE", [ins.op for ins in code])

    def test_demo_shrinks_further_with_propagation(self):
        with open(f"{ROOT}/examples/demo.ml", encoding="utf-8") as f:
            src = f.read()
        r = run_pipeline(src)
        self.assertLess(r["optimizer"]["after"], 70)   # 87 unoptimized, 82 with folding alone
        self.assertEqual(r["output"], ["16", "3", "1", "15", "120", "6", "-1", "4", "-1", "2", "-1"])

    def test_pipeline_includes_ir(self):
        r = run_pipeline("x = 1;\nprint x + 1;")
        self.assertEqual(r["ir"]["procedures"][0]["blocks"][0]["optimized"], ["x = 1", "t1 = 2", "print 2"])
        self.assertEqual(r["ir"]["stats"]["constant_reads"], 1)


if __name__ == "__main__":
    unittest.main()
