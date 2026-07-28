"""Scorer for `nanoloop run --optimize`. Lower is better.

Correctness is NOT this function's job — `tests/` refuses anything that changes
the unitary, and the crew runs them as a gate before this is ever consulted. A
scorer that also had to judge correctness would be tempted to return a great
score for a circuit that computes the wrong thing, which is how you teach a
search that deleting the work is an excellent optimisation.

That division of labour only holds while the gate actually exists. It did not:
this directory shipped with no tests and no `pyproject.toml`, so the optimum of
this function — an empty circuit, cost 0 — was unopposed by anything except
`preflight` refusing to start. `tests/test_target.py` closes that, and pins the
empty circuit as the counter-example.

Returns None when the module cannot even be loaded: unusable is not the same as
expensive, and None takes the candidate out of the running entirely.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# A two-qubit gate is roughly an order of magnitude worse than a single-qubit
# one on current hardware — more error, more time, and the qubit may not survive
# either. `circuits.py` in the sibling example says exactly that, and plain gate
# count cannot express it: three gates with one CX and three gates with two CX
# are not the same circuit. Counting is by ARITY, never by gate name, so nothing
# escapes by calling itself `cz` instead of `cx`.
TWO_QUBIT_WEIGHT = 10


def cost(qc) -> float:
    """Weighted gate cost of a circuit. Lower is better."""
    total = 0.0
    for inst in qc.data:
        total += TWO_QUBIT_WEIGHT if len(inst.qubits) >= 2 else 1
    return total


def score(workspace) -> float | None:
    target = Path(workspace) / "target.py"
    if not target.exists():
        return None
    spec = importlib.util.spec_from_file_location("scored_target", target)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return cost(module.build())
    except Exception:  # noqa: BLE001 - any failure means "not a usable candidate"
        return None
