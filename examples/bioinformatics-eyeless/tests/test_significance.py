"""The null has to be able to say no.

A significance test that calls everything significant is not a test, it is
decoration — so the negative case is pinned here as hard as the positive one.
"""

import random

from sequences import EYELESS_DROME, PAX6_HUMAN
from significance import shuffled_scores, significance, verdict


def scramble(seq: str, seed: int) -> str:
    letters = list(seq)
    random.Random(seed).shuffle(letters)
    return "".join(letters)


def test_the_real_pair_beats_every_shuffle():
    """The claim the whole example rests on, measured rather than asserted."""
    r = significance(EYELESS_DROME, PAX6_HUMAN, trials=30)
    assert r["beat_every_shuffle"]
    assert r["z_score"] > 20
    assert r["score"] > r["null_max"] * 5


def test_a_scrambled_subject_is_not_significant():
    """The control on the control: destroy the order and the signal must go.

    Same amino acids, same frequencies, no ancestry. If this came out
    significant the method would be calling any two sequences of this
    composition related, and the test above would prove nothing.
    """
    r = significance(EYELESS_DROME, scramble(PAX6_HUMAN, seed=42), trials=30, seed=1)
    assert not r["beat_every_shuffle"]
    assert r["z_score"] < 5


def test_shuffling_preserves_composition():
    """That is the whole point. If shuffling changed the composition, the null
    would be answering a different question than the one being asked."""
    assert sorted(scramble(PAX6_HUMAN, seed=3)) == sorted(PAX6_HUMAN)


def test_it_is_deterministic():
    """Same seed, same numbers — otherwise the example reports something
    different on every machine and none of it can be cited."""
    a = significance(EYELESS_DROME, PAX6_HUMAN, trials=10, seed=7)
    b = significance(EYELESS_DROME, PAX6_HUMAN, trials=10, seed=7)
    assert a == b


def test_a_different_seed_gives_the_same_conclusion():
    """The finding must not live in the seed."""
    for seed in (0, 1, 99):
        assert significance(EYELESS_DROME, PAX6_HUMAN, trials=10, seed=seed)["beat_every_shuffle"]


def test_every_shuffle_is_a_different_one():
    """A loop that shuffled once and scored it 100 times would produce a null
    with sd 0 and an infinite z-score, which is a bug that looks like a result."""
    assert len(set(shuffled_scores(EYELESS_DROME, PAX6_HUMAN, trials=10))) > 1


def test_the_p_value_is_reported_as_a_bound_not_a_point():
    """With 30 trials the smallest honest statement is 1/30, never 0."""
    assert significance(EYELESS_DROME, PAX6_HUMAN, trials=30)["p_value_upper_bound"] == 1 / 30


def test_verdict_reads_as_a_sentence():
    assert "standard deviations" in verdict(significance(EYELESS_DROME, PAX6_HUMAN, trials=10))


# --- a block has to beat the blocks chance produces --------------------------


def test_the_linker_block_is_below_the_noise_floor():
    """Reported as "linker, far freer to mutate" at 19% identity. Shuffled PAX6
    produces blocks averaging ~26%, so that block is worse than average noise:
    nothing survived there at all."""
    from conserved import conserved_blocks
    from significance import above_noise, block_identity_null

    null = block_identity_null(EYELESS_DROME, PAX6_HUMAN, trials=20)
    blocks = conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    weakest = min(blocks, key=lambda b: b["percent_identity"])

    assert weakest["percent_identity"] < sum(null) / len(null)
    assert not above_noise(weakest["percent_identity"], null)


def test_the_real_domains_do_beat_the_noise_floor():
    from conserved import conserved_blocks
    from significance import above_noise, block_identity_null

    null = block_identity_null(EYELESS_DROME, PAX6_HUMAN, trials=20)
    for b in conserved_blocks(EYELESS_DROME, PAX6_HUMAN):
        if b["length"] > 100:
            assert above_noise(b["percent_identity"], null), b


def test_chance_really_does_produce_long_blocks():
    """The premise of the whole check: a local aligner extends while the score
    stays positive, so blocks are not evidence on their own."""
    from significance import block_identity_null

    assert len(block_identity_null(EYELESS_DROME, PAX6_HUMAN, trials=20)) > 10
