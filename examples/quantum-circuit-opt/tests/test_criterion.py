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
import os
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


def redundant() -> QuantumCircuit:
    """`circuits.py` as it SHIPS, written out here rather than imported.

    This is the correction that matters, and it cost three failed runs to find.
    The test below used to call `circuits.prepare_state()` — the very function
    the crew is asked to optimise — and assert that it fails the criterion. True
    while the file is unoptimised, and false the instant the task is done: the
    test went red on the correct answer, the gate reverted the edit, and the run
    burned its budget re-solving a problem it had already solved.

    A test that asserts "the current state is bad" stops being a test the moment
    someone fixes the current state. Freeze the input.
    """
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(0, 1)
    qc.cx(0, 1)
    qc.x(1)
    qc.x(1)
    qc.rz(0.5, 0)
    return qc


def test_the_intended_answer_passes():
    run_criterion(intended())


def test_a_redundant_circuit_fails():
    """Equivalent to the reference, and three times the two-qubit cost."""
    with pytest.raises(AssertionError):
        run_criterion(redundant())


@pytest.mark.skipif(
    os.environ.get("NANOLOOP_META_TEST") == "1",
    # Without this the test copies the suite it lives in and runs it, which
    # copies it again. Found the direct way: 300 s of recursion.
    reason="running inside its own copy of the suite",
)
def test_the_gates_stay_green_once_the_task_is_solved(tmp_path):
    """The meta-test that would have caught the bug above.

    The example is only an example if solving it leaves the suite green. This
    copies the workspace, writes the optimal circuit into it, and runs the whole
    suite there — which is exactly what the crew's gate does after an edit. If
    any test here encodes "the circuit is still redundant", this goes red.
    """
    import shutil
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    work = tmp_path / "solved"
    shutil.copytree(
        root, work, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache")
    )
    (work / "circuits.py").write_text(
        "from qiskit import QuantumCircuit\n\n\n"
        "def prepare_state() -> QuantumCircuit:\n"
        '    """Entangle two qubits and rotate the first."""\n'
        "    qc = QuantumCircuit(2)\n"
        "    qc.h(0)\n"
        "    qc.cx(0, 1)\n"
        "    qc.rz(0.5, 0)\n"
        "    return qc\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(work),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "NANOLOOP_META_TEST": "1"},
    )
    assert proc.returncode == 0, f"solving the task turns the suite red:\n{proc.stdout[-1500:]}"


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
