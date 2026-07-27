from qiskit import QuantumCircuit


def build() -> QuantumCircuit:
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.rz(0.7, 0)
    qc.cx(0, 1)
    return qc
