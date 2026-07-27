"""The circuit must keep computing exactly what it computes today."""

from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

from circuits import prepare_state


def reference() -> QuantumCircuit:
    """What prepare_state means, written out plainly. Frozen on purpose."""
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    qc.rz(0.5, 0)
    return qc


def test_unitary_is_unchanged():
    assert Operator(prepare_state()).equiv(Operator(reference()))
