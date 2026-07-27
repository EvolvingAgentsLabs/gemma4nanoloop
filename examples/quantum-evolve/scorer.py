"""Scorer for `nanoloop run --optimize`. Lower is better.

Correctness is NOT this function's job — the gates and the acceptance criteria
already refuse anything that changes the unitary. A scorer that also had to
judge correctness would be tempted to return a great score for a circuit that
computes the wrong thing, which is how you teach a search that deleting the
work is an excellent optimisation.

Returns None when the module cannot even be loaded: unusable is not the same as
expensive, and None takes the candidate out of the running entirely.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


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
        qc = module.build()
        return float(sum(qc.count_ops().values()))
    except Exception:  # noqa: BLE001 - any failure means "not a usable candidate"
        return None
