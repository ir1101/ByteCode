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


class LivenessTests(unittest.TestCase):
    def test_live_sets_around_a_loop(self):
        blocks = main_blocks("i = 0;\nwhile i < 3 { i = i + 1; }\nprint i;")
        self.assertEqual(blocks[0]["live_in"], [])
        self.assertEqual(blocks[0]["live_out"], ["i"])
        self.assertEqual(blocks[1]["live_in"], ["i"])       # the condition reads it
        self.assertEqual(blocks[3]["live_out"], [])         # nothing is read after the program ends

    def test_overwritten_value_is_a_dead_store(self):
        (block,) = main_blocks("x = 1;\nx = 2;\nprint x;")
        self.assertEqual(block["dead"], [0])

    def test_value_read_on_one_path_is_live(self):
        blocks = main_blocks("x = 1;\nif n { x = 2; }\nprint x;")
        self.assertEqual(blocks[0]["dead"], [])

    def test_a_global_read_by_a_called_function_is_live(self):
        procs = ir_of("g = 1;\nfunc f() { return g; }\nprint f();\ng = 2;").to_dict()["procedures"]
        self.assertEqual(procs[0]["blocks"][0]["dead"], [3])   # only g = 2, after the last call

    def test_function_locals_die_at_return(self):
        procs = ir_of("func f(a) { b = a; b = 2; return a; }\nprint f(1);").to_dict()["procedures"]
        self.assertEqual(procs[1]["blocks"][0]["dead"], [0, 1])

    def test_temps_never_clash_with_a_variable_named_t1(self):
        (block,) = main_blocks("t1 = 100;\ny = 2 * 3 + t1;\nprint y;")
        self.assertEqual(block["optimized"][-1], "print 106")
        self.assertEqual(run_pipeline("t1 = 100;\ny = 2 * 3 + t1;\nprint y;")["output"], ["106"])

    def test_optimized_view_drops_stores_made_dead_by_propagation(self):
        (block,) = main_blocks("x = 10;\ny = x * 2;\nprint y;")
        self.assertEqual(block["optimized"], ["x = 10", "y = 20", "print 20"])
        self.assertEqual(block["optimized_dead"], [0, 1])

    def test_a_store_that_might_fail_is_never_removed(self):
        (block,) = main_blocks("d = 0;\nx = 5 / d;\nprint 1;")
        self.assertNotIn(1, block["optimized_dead"])          # x = 5 / 0 must still raise


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
        block = r["ir"]["procedures"][0]["blocks"][0]
        self.assertEqual(block["optimized"], ["x = 1", "t1 = 2", "print 2"])
        self.assertEqual(block["optimized_dead"], [0, 1])
        self.assertEqual(r["ir"]["stats"]["constant_reads"], 1)
        self.assertEqual(r["ir"]["stats"]["removed_stores"], 2)


if __name__ == "__main__":
    unittest.main()
