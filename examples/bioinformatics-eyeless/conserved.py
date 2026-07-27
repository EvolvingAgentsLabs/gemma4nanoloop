"""Encuentra los bloques conservados entre dos proteínas.

El experimento del ojo de la mosca, de *Developing Bioinformatics Computer
Skills* (Gibas & Jambeck, O'Reilly 2001): `eyeless` de Drosophila y el gen
humano de la aniridia (hoy PAX6) no comparten nombre, pero sí comparten
secuencia. Un alineamiento local lo revela; una búsqueda por palabras jamás.
"""

from Bio import Align
from Bio.Align import substitution_matrices


def align(query: str, subject: str):
    """Alineamiento local con los parámetros clásicos de BLASTP."""
    aligner = Align.PairwiseAligner(mode="local")
    aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
    aligner.open_gap_score = -11
    aligner.extend_gap_score = -1
    return aligner.align(query, subject)[0]


def conserved_blocks(query: str, subject: str, min_length: int = 20):
    """Bloques alineados de al menos `min_length` residuos.

    Devuelve dicts con coordenadas **1-based e inclusivas**, que es como las
    reporta BLAST y como las escribe todo el mundo en un paper.
    """
    alignment = align(query, subject)
    blocks = []
    for (qs, qe), (ss, se) in zip(*alignment.aligned):
        if qe - qs < min_length:
            continue
        q_seg, s_seg = query[qs:qe], subject[ss:se]
        identities = sum(1 for a, b in zip(q_seg, s_seg) if a == b)
        blocks.append(
            {
                # +1 porque Biopython devuelve medio-abiertas 0-based y aquí
                # se documentan 1-based inclusivas, como las reporta BLAST.
                # Este es EL bug clásico de la bioinformática; ver README.
                "query_start": qs + 1,
                "query_end": qe,
                "subject_start": ss + 1,
                "subject_end": se,
                "length": qe - qs,
                "identities": identities,
                "percent_identity": round(100 * identities / (qe - qs), 1),
            }
        )
    return blocks
