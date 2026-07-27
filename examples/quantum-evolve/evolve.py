"""An AlphaEvolve-shaped loop: propose many, score all, keep the best, repeat.

This is NOT what nanoloop's crew does, and the difference is the point.

    crew         propose -> first candidate that PASSES wins -> stop
                 optimises for CORRECT
    this loop    propose N -> score every one -> keep the best -> iterate
                 optimises for BEST SUBJECT TO CORRECT

The crew has best-of-N already, but it takes the first sample that clears the
gate, because for a bug fix "correct" is the whole requirement. Optimisation has
no such stopping point: every candidate that is correct is still comparable to
every other, and stopping at the first one throws the search away.

The evaluator is the same idea as `Acceptance.check`, split in two:

    valid   Operator(candidate).equiv(Operator(reference))   a hard gate
    score   total gate count                                 a gradient

A candidate that is not valid scores nothing regardless of how short it is —
otherwise the loop learns that deleting the circuit is an excellent
optimisation.

    python examples/quantum-evolve/evolve.py --generations 3 --candidates 3
"""

from __future__ import annotations

import argparse
import ast
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qiskit import QuantumCircuit, transpile  # noqa: E402
from qiskit.quantum_info import Operator  # noqa: E402

from nanoloop import calllog, crew, model_ollama  # noqa: E402

HERE = Path(__file__).resolve().parent

SYSTEM = """You output one complete Python file containing a function `build()`
that returns a Qiskit QuantumCircuit with FEWER GATES than the one you are shown.

Write real, runnable Python. Every qubit index is a literal integer: 0 or 1.
Never write a placeholder name where a number belongs.

Apply these identities:
- two identical self-inverse gates in a row cancel: h h, x x, cx cx on the same pair
- two rz on the same qubit merge into one rz with the angles added
- an rz on the CONTROL qubit of a cx commutes through it, which can bring two rz
  together so they can then merge

The unitary must not change. It is checked exactly; a wrong circuit scores zero.

Start the file with `from qiskit import QuantumCircuit`.

Output JSON matching the schema. Nothing else."""


def reference() -> QuantumCircuit:
    from target import build

    return build()


def evaluate(code: str, ref_op: Operator) -> tuple[bool, int, str]:
    """(valid, score, why). Score is total gate count; lower is better."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, 0, f"syntax: {e.msg}"
    ns: dict = {}
    try:
        exec(compile(code, "<candidate>", "exec"), ns)  # noqa: S102
        qc = ns["build"]()
    except Exception as e:  # noqa: BLE001
        return False, 0, f"{type(e).__name__}: {e}"
    if not isinstance(qc, QuantumCircuit):
        return False, 0, "build() did not return a QuantumCircuit"
    try:
        if not Operator(qc).equiv(ref_op):
            return False, 0, "unitary changed"
    except Exception as e:  # noqa: BLE001
        return False, 0, f"could not compare: {e}"
    return True, sum(qc.count_ops().values()), ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--candidates", type=int, default=3)
    args = ap.parse_args()

    sys.path.insert(0, str(HERE))
    calllog.reset_clock()

    original = reference()
    ref_op = Operator(original)
    start_score = sum(original.count_ops().values())

    baseline = transpile(original, optimization_level=3, basis_gates=["h", "rz", "cx", "x"])
    target_score = sum(baseline.count_ops().values())

    print(f"original    {start_score} gates, depth {original.depth()}")
    print(f"transpiler  {target_score} gates, depth {baseline.depth()}   <- the bar to match\n")

    best_code = (HERE / "target.py").read_text()
    best_score = start_score
    t0 = time.monotonic()
    calls = 0

    for gen in range(args.generations):
        print(f"generation {gen + 1}")
        improved = False
        for c in range(args.candidates):
            # Temperature rises across the population: candidate 0 is the greedy
            # continuation of the current best, the rest explore around it.
            temperature = 0.0 if c == 0 else 0.3 * c
            prompt = (
                f"# Current circuit ({best_score} gates)\n```python\n{best_code}\n```\n\n"
                f"Rewrite it with fewer gates. Best known so far: {best_score}."
            )
            try:
                raw = model_ollama.chat(
                    SYSTEM,
                    prompt,
                    phase="build",
                    num_ctx=8192,
                    temperature=temperature,
                    schema=crew.schema_of(crew.NewFile),
                )
                calls += 1
            except Exception as e:  # noqa: BLE001
                print(f"  cand {c}: call failed — {type(e).__name__}")
                continue

            from nanoloop.planner import _extract_json

            try:
                code = crew.NewFile.model_validate(
                    {"path": "target.py", **_extract_json(raw)}
                ).content
            except Exception:  # noqa: BLE001
                print(f"  cand {c}: unparseable")
                continue

            valid, score, why = evaluate(code, ref_op)
            mark = "  " if not valid else ("**" if score < best_score else "  ")
            print(
                f"  cand {c}: {'valid' if valid else 'INVALID':<7} "
                f"{score if valid else '-':>3} gates {mark}{why}"
            )
            if valid and score < best_score:
                best_score, best_code, improved = score, code, True

        print(f"  best so far: {best_score} gates\n")
        if best_score <= target_score:
            print("reached the transpiler's result — stopping\n")
            break
        if not improved:
            # No candidate beat the incumbent. More generations of the same
            # prompt will not either; a real evolutionary system would mutate
            # the strategy here, which is beyond this example.
            print("  no improvement this generation\n")

    elapsed = time.monotonic() - t0
    print("=== result ===")
    print(f"  {start_score} -> {best_score} gates   (transpiler: {target_score})")
    print(f"  {calls} model calls, {elapsed:.0f}s")
    verdict = (
        "matched the transpiler"
        if best_score <= target_score
        else f"did NOT match the transpiler ({best_score} vs {target_score})"
    )
    print(f"  {verdict}")
    (HERE / "best.py").write_text(best_code)
    print("  best candidate written to examples/quantum-evolve/best.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
