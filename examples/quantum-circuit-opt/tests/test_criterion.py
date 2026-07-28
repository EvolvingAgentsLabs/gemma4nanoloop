"""The shipped acceptance criterion, run against circuits designed to cheat it.

An oracle nobody tests is a claim, not an oracle. This loads `criteria.json`
exactly as the crew does and executes it against four circuits: the intended
answer, two that are equivalent but WORSE, and one that is simply wrong.

The two "worse" cases are the reason this file exists. The criterion used to
name gates — `cx <= 1` and `x == 0` — so a circuit could pass by renaming its
way out of the check while getting bigger:

    cz + hadamards        5 gates, zero 'cx'   passed
    ten cancelling y      23 gates, zero 'x'   passed

Both preserve the unitary. Neither is an improvement, which is the half of the
criterion that was supposed to be doing the work.
"""

import json
from pathlib import Path

import pytest
from qiskit import QuantumCircuit

import circuits

CRITERION = json.loads((Path(__file__).parent.parent / "criteria.json").read_text())[0]["check"]


def run_criterion(qc: QuantumCircuit) -> None:
    """Execute the real criterion against `qc`. Raises AssertionError if unmet."""
    circuits.prepare_state = lambda: qc  # what the criterion imports
    exec(compile(CRITERION, "<criterion>", "exec"), {"__name__": "__main__"})  # noqa: S102


@pytest.fixture(autouse=True)
def _restore():
    original = circuits.prepare_state
    yield
    circuits.prepare_state = original


def intended() -> QuantumCircuit:
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    qc.rz(0.5, 0)
    return qc


def test_the_intended_answer_passes():
    run_criterion(intended())


def test_the_original_redundant_circuit_fails():
    """It is equivalent to itself, obviously — it must fail on cost."""
    with pytest.raises(AssertionError):
        run_criterion(circuits.prepare_state())


def test_a_renamed_two_qubit_gate_does_not_get_a_free_pass():
    """cz + hadamards: same unitary, zero 'cx', five gates instead of three."""
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.h(1)
    qc.cz(0, 1)
    qc.h(1)
    qc.rz(0.5, 0)
    with pytest.raises(AssertionError):
        run_criterion(qc)


def test_padding_with_a_gate_the_check_does_not_name_fails():
    """Ten cancelling Y pairs: same unitary, zero 'x', twenty-three gates."""
    qc = intended()
    for _ in range(10):
        qc.y(1)
        qc.y(1)
    with pytest.raises(AssertionError):
        run_criterion(qc)


def test_a_circuit_with_the_wrong_unitary_fails():
    """The correctness half, still doing its job."""
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    with pytest.raises(AssertionError):
        run_criterion(qc)


def test_an_empty_circuit_fails():
    """Cheap is not the same as correct — the trap a lone cost metric falls into."""
    with pytest.raises(AssertionError):
        run_criterion(QuantumCircuit(2))
