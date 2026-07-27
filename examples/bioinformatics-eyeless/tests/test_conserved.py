"""El paired domain debe aparecer donde la biología dice que está.

Coordenadas 1-based inclusivas, como las reporta BLAST. Los números NO son los
del libro de 2001 —aquellas entradas de base de datos ya no existen— sino los
que dan las entradas actuales de UniProt, que están vendidas en sequences.py
para que este test siga significando lo mismo dentro de cinco años.
"""

from conserved import conserved_blocks
from sequences import EYELESS_DROME, PAX6_HUMAN


def test_paired_domain_is_found():
    blocks = conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    assert blocks, "no se encontró ningún bloque conservado"
    paired = max(blocks, key=lambda b: b["percent_identity"])
    # eyeless 57-189 frente a PAX6 5-137, 1-based inclusivo.
    assert paired["query_start"] == 57
    assert paired["query_end"] == 189
    assert paired["subject_start"] == 5
    assert paired["subject_end"] == 137
    assert paired["percent_identity"] > 85


def test_the_conserved_block_is_long_enough_to_be_a_domain():
    blocks = conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    assert max(b["length"] for b in blocks) > 100
