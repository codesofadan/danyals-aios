"""A tiny, dependency-free mutation tester (mutmut 3.x has no native Windows
support). It generates mutants of a target module's FUNCTION bodies (module-level
reference data is left alone - mutating a label string is not a logic bug), runs
the module's unit test file against each, and reports the mutation score.

A mutant is KILLED if the test file fails with it applied, SURVIVED if the tests
still pass (an assertion gap). Survivors are the actionable output.

Usage:
    ./.venv/Scripts/python tests/mutation/run_mutation.py app/rbac/matrix.py tests/test_rbac_matrix.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_CMP_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
}
_BOOL_SWAP: dict[type[ast.boolop], type[ast.boolop]] = {ast.And: ast.Or, ast.Or: ast.And}


class _MutantMaker(ast.NodeTransformer):
    """Applies exactly ONE mutation (the one at ``target_index``) per instantiation."""

    def __init__(self, target_index: int) -> None:
        self.target = target_index
        self.count = -1
        self.applied: str | None = None
        self._in_func = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self._in_func += 1
        self.generic_visit(node)
        self._in_func -= 1
        return node

    def _fire(self, desc: str) -> bool:
        if not self._in_func:
            return False
        self.count += 1
        if self.count == self.target:
            self.applied = desc
            return True
        return False

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            swap = _CMP_SWAP.get(type(op))
            if swap and self._fire(f"cmp {type(op).__name__}->{swap.__name__}"):
                node.ops[i] = swap()
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        swap = _BOOL_SWAP.get(type(node.op))
        if swap and self._fire(f"bool {type(node.op).__name__}->{swap.__name__}"):
            node.op = swap()
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self._fire("drop 'not'"):
            return node.operand
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, bool):
            if self._fire(f"bool const {node.value}->{not node.value}"):
                return ast.copy_location(ast.Constant(value=not node.value), node)
        elif isinstance(node.value, int) and self._fire(f"int {node.value}->{node.value + 1}"):
            return ast.copy_location(ast.Constant(value=node.value + 1), node)
        return node


def _count_mutations(tree: ast.AST) -> int:
    maker = _MutantMaker(target_index=-2)  # never fires; just counts
    maker.visit(tree)
    return maker.count + 1


def main() -> int:
    module_path = Path(sys.argv[1])
    test_path = sys.argv[2]
    # Keep the ORIGINAL bytes so the restore is byte-exact (no CRLF/LF drift on
    # Windows, which would otherwise leave the target file spuriously modified).
    original_bytes = module_path.read_bytes()
    original = original_bytes.decode("utf-8")
    total = _count_mutations(ast.parse(original))
    print(f"module={module_path}  test={test_path}  mutants={total}")

    killed, survived = 0, []
    try:
        for i in range(total):
            tree = ast.parse(original)
            maker = _MutantMaker(target_index=i)
            mutated = ast.fix_missing_locations(maker.visit(tree))
            module_path.write_text(ast.unparse(mutated), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", test_path, "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                survived.append((i, maker.applied))
                print(f"  [{i:3}] SURVIVED  {maker.applied}")
            else:
                killed += 1
    finally:
        module_path.write_bytes(original_bytes)  # ALWAYS restore, byte-exact

    score = killed / total * 100 if total else 100.0
    print(f"\nMUTATION SCORE: {killed}/{total} killed = {score:.1f}%")
    if survived:
        print("SURVIVORS (assertion gaps):")
        for idx, desc in survived:
            print(f"  #{idx}: {desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
