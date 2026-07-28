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


def identity_over(query: str, subject: str, s_start: int, s_end: int) -> dict:
    """Identity restricted to a range of SUBJECT positions (1-based, inclusive).

    WHY THIS EXISTS, and it is the most important correction in this example.

    `conserved_blocks` returns the ungapped segments of ONE local alignment.
    BLAST reports HSPs: separate local alignments, each with its own E-value.
    Those are not the same thing, and treating them as if they were understates
    the biology badly here.

    The homeodomain sits at PAX6 208-267 and is 90% identical to the fly's. But
    the ungapped block containing it runs 182-327, so it also carries flanks at
    46% and 35% — and the block as a whole reports 60%. Label that block
    "homeodomain" and you have just described one of the most conserved
    DNA-binding motifs known as barely more conserved than average. The book's
    own numbers (80 aa at 85%) agree with 90%, not with 60%.

    So: the alignment still finds the blocks on its own, unaided. This function
    only answers a narrower question afterwards — how conserved is the annotated
    domain itself — and the two are reported separately in discover.py so the
    discovery never leans on the annotation.
    """
    alignment = align(query, subject)
    aligned = identities = 0
    for (qs, qe), (ss, se) in zip(*alignment.aligned):
        for i in range(qe - qs):
            if s_start <= ss + i + 1 <= s_end:
                aligned += 1
                identities += query[qs + i] == subject[ss + i]
    return {
        "aligned": aligned,
        "identities": identities,
        "percent_identity": round(100 * identities / aligned, 1) if aligned else 0.0,
    }


def alignment_totals(query: str, subject: str) -> dict:
    """Every aligned residue, not only the ones inside long blocks.

    `conserved_blocks` filters to >= min_length, so summing over its output and
    calling the result "the aligned residues" counts a filtered subset: 311 of
    the 389 residues this alignment actually pairs up.
    """
    alignment = align(query, subject)
    aligned = identities = 0
    for (qs, qe), (ss, se) in zip(*alignment.aligned):
        aligned += qe - qs
        identities += sum(1 for a, b in zip(query[qs:qe], subject[ss:se]) if a == b)
    return {
        "aligned": aligned,
        "identities": identities,
        "percent_identity": round(100 * identities / aligned, 1) if aligned else 0.0,
    }


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
