"""The correctness gate this directory claimed to have and did not.

`scorer.py` explains that judging correctness is not its job because "the gates
and the acceptance criteria already refuse anything that changes the unitary".
That was true of the crew in general and false of this directory in particular:
there were no tests here at all, and no `pyproject.toml` either, so

  - `preflight` refused to start (which is what accidentally prevented disaster),
  - and the scorer's optimum, unopposed, is an EMPTY circuit. It scores 0.

A cost metric with no correctness gate does not optimise a circuit. It deletes
it. These tests are the gate that makes the scorer's stated division of labour
actually true.
"""

from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

import best
import target
from scorer import cost


def reference() -> QuantumCircuit:
    """What target.build() means, written out. Frozen on purpose.

    Derived by hand, and the derivation IS the example: the trailing `h h` and
    the `x x` cancel, the last two `cx` cancel, and then `rz(0.4)` commutes back
    through the remaining `cx` because it sits on the CONTROL qubit — which is
    what finally lets 0.3 and 0.4 merge into 0.7.
    """
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.rz(0.7, 0)
    qc.cx(0, 1)
    return qc


def test_the_target_computes_what_the_reference_computes():
    assert Operator(target.build()).equiv(Operator(reference()))


def test_the_committed_best_is_still_equivalent():
    """`evolve.py` writes this file. If a run ever writes a wrong circuit here,
    or overwrites a good one with the unimproved original, this fails."""
    assert Operator(best.build()).equiv(Operator(reference()))


def test_the_committed_best_is_actually_better():
    assert cost(best.build()) < cost(target.build())
    assert best.build().size() < target.build().size()


def test_an_empty_circuit_is_cheap_and_wrong():
    """The failure mode the scorer cannot see on its own, pinned here instead."""
    empty = QuantumCircuit(2)
    assert cost(empty) == 0  # the global optimum of the cost function
    assert not Operator(empty).equiv(Operator(reference()))  # and useless


def test_cost_prefers_fewer_two_qubit_gates_at_equal_size():
    """The stated motivation is that two-qubit gates are the expensive ones.
    Total gate count cannot express that; both of these have three gates."""
    one = QuantumCircuit(2)
    one.h(0)
    one.rz(0.7, 0)
    one.cx(0, 1)

    two = QuantumCircuit(2)
    two.h(0)
    two.cx(0, 1)
    two.cx(1, 0)

    assert one.size() == two.size()
    assert cost(one) < cost(two)


# --- the run must not damage what it is supposed to improve ------------------


def test_a_run_that_improves_nothing_leaves_best_py_alone(monkeypatch, capsys):
    """`best_code` starts as target.py's contents and used to be written to
    best.py unconditionally, so a run where every candidate failed replaced the
    committed 3-gate result with the 10-gate original."""
    import sys
    from pathlib import Path

    import evolve

    before = (Path(evolve.HERE) / "best.py").read_text()

    def refuse(*a, **k):
        raise RuntimeError("no model here")

    monkeypatch.setattr(evolve.model_ollama, "chat", refuse)
    monkeypatch.setattr(sys, "argv", ["evolve.py", "--generations", "1", "--candidates", "1"])
    evolve.main()

    assert (Path(evolve.HERE) / "best.py").read_text() == before
    assert "left untouched" in capsys.readouterr().out


def test_the_evaluator_survives_a_candidate_that_never_returns(monkeypatch):
    """It used to exec() candidates in-process with no timeout, so a generated
    `while True:` hung the run with no way to distinguish it from a slow model."""
    from qiskit.quantum_info import Operator

    import evolve

    monkeypatch.setattr(evolve, "EVAL_TIMEOUT", 3)  # the real one is 30
    forever = "from qiskit import QuantumCircuit\ndef build():\n    while True: pass\n"
    valid, _, why = evolve.evaluate(forever, Operator(reference()))
    assert not valid
    assert "did not finish" in why
