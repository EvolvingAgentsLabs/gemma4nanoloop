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
