"""Find the conserved blocks between two proteins.

The fly's eye experiment, from *Developing Bioinformatics Computer Skills*
(Gibas & Jambeck, O'Reilly 2001): Drosophila `eyeless` and the human aniridia
gene (today PAX6) share no name, but they do share sequence. A local alignment
reveals it; a word search never would.
"""

from Bio import Align
from Bio.Align import substitution_matrices


def align(query: str, subject: str):
    """Local alignment with the classic BLASTP parameters."""
    aligner = Align.PairwiseAligner(mode="local")
    aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
    aligner.open_gap_score = -11
    aligner.extend_gap_score = -1
    return aligner.align(query, subject)[0]


def conserved_blocks(query: str, subject: str, min_length: int = 20):
    """Aligned blocks of at least `min_length` residues.

    Returns dicts with **1-based, inclusive** coordinates — the way BLAST
    reports them and the way everyone writes them in a paper.
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
                # +1 because Biopython returns 0-based half-open ranges while
                # this function documents 1-based inclusive ones, as BLAST does.
                # This is THE classic bioinformatics bug; see the README.
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
