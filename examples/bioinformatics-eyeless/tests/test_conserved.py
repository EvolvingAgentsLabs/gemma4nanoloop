"""The paired domain must appear where the biology says it is.

1-based inclusive coordinates, as BLAST reports them. The numbers are NOT the
book's from 2001 — those database entries no longer exist — but the ones the
current UniProt entries give, vendored in sequences.py so this test still means
the same thing in five years.
"""

from conserved import conserved_blocks
from sequences import EYELESS_DROME, PAX6_HUMAN


def test_paired_domain_is_found():
    blocks = conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    assert blocks, "no conserved block was found"
    paired = max(blocks, key=lambda b: b["percent_identity"])
    # eyeless 57-189 against PAX6 5-137, 1-based inclusive.
    assert paired["query_start"] == 57
    assert paired["query_end"] == 189
    assert paired["subject_start"] == 5
    assert paired["subject_end"] == 137
    assert paired["percent_identity"] > 85


def test_the_conserved_block_is_long_enough_to_be_a_domain():
    blocks = conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    assert max(b["length"] for b in blocks) > 100


# --- the block is not the domain (the correction that mattered) --------------


def test_the_homeodomain_is_ninety_percent_not_sixty():
    """The bug this pins: the ungapped block containing the homeodomain runs
    PAX6 182-327 and reports 60%, because it also carries flanks at 46% and 35%.
    The domain itself is 90%, and the book's own numbers (80 aa at 85%) agree
    with that, not with the block's."""
    from conserved import identity_over

    d = identity_over(EYELESS_DROME, PAX6_HUMAN, 208, 267)
    assert d["aligned"] == 60
    assert d["percent_identity"] > 85

    block = next(
        b
        for b in conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
        if b["subject_start"] < 208 < b["subject_end"]
    )
    assert block["percent_identity"] < 65  # the block dilutes it by 30 points
    assert block["length"] > 2 * d["aligned"]


def test_the_paired_domain_agrees_with_its_block():
    """It only looks fine because a gap happens to fall just after it — which is
    why the domain has to be measured, not assumed from the block."""
    from conserved import identity_over

    d = identity_over(EYELESS_DROME, PAX6_HUMAN, 4, 136)
    assert d["percent_identity"] > 90


def test_totals_count_the_whole_alignment_not_the_filtered_blocks():
    """ "217 of 311 aligned residues" counted only blocks >= 20aa — 80% of them."""
    from conserved import alignment_totals

    whole = alignment_totals(EYELESS_DROME, PAX6_HUMAN)
    in_blocks = sum(b["length"] for b in conserved_blocks(EYELESS_DROME, PAX6_HUMAN))
    assert whole["aligned"] > in_blocks
    assert whole["identities"] > sum(
        b["identities"] for b in conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    )
