"""The circuit under evolution.

Redundant in ways that need REORDERING before they cancel, not just adjacent
pairs: the two rz on qubit 0 can merge, but only once you notice the cx between
them commutes with an rz on the control.
"""

from qiskit import QuantumCircuit


def build() -> QuantumCircuit:
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.rz(0.3, 0)
    qc.cx(0, 1)
    qc.rz(0.4, 0)
    qc.cx(0, 1)
    qc.cx(0, 1)
    qc.x(1)
    qc.x(1)
    qc.h(0)
    qc.h(0)
    return qc
