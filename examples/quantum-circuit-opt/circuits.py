"""Circuits under optimisation.

`prepare_state` is deliberately redundant: it applies gates that cancel each
other out. It computes the right thing, slowly. On real hardware every extra
two-qubit gate is error and time a qubit may not survive.
"""

from qiskit import QuantumCircuit


def prepare_state() -> QuantumCircuit:
    """Entangle two qubits and rotate the first.

    The mathematics of what this returns must not change. How many gates it
    takes to get there may.
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
