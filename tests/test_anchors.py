"""Tests for anchor location — the Phase 2 viability mechanism."""

from __future__ import annotations

import pytest

from nanoloop import anchors
from nanoloop.anchors import AnchorError, Match

SRC = """def alpha():
    value = 1
    return value


def beta():
    value = 2
    return value
"""


def test_exact_unique_match():
    res = anchors.locate(SRC, "    value = 1")
    assert res.kind is Match.EXACT
    assert SRC[res.start : res.end] == "    value = 1"


def test_repeated_text_is_ambiguous_not_first_wins():
    """Picking the first of two matches is how you silently corrupt a repo."""
    with pytest.raises(AnchorError) as exc:
        anchors.locate(SRC, "    return value")
    assert exc.value.kind is Match.AMBIGUOUS
    assert exc.value.candidates == 2


def test_missing_anchor_raises_not_found():
    with pytest.raises(AnchorError) as exc:
        anchors.locate(SRC, "def gamma():")
    assert exc.value.kind is Match.NOT_FOUND


def test_fuzzy_is_off_by_default():
    """Measure exact FIRST — fuzzy-by-default would destroy the measurement."""
    assert anchors.FUZZY_ENABLED is False
    with pytest.raises(AnchorError):
        anchors.locate(SRC, "def alpha( ):")  # near-miss, rejected without fuzzy


def test_fuzzy_recovers_a_near_miss():
    res = anchors.locate(SRC, "def alpha( ):\n  value = 1\n  return value", fuzzy=True)
    assert res.kind is Match.FUZZY
    assert res.score >= anchors.FUZZY_THRESHOLD


def test_fuzzy_still_refuses_two_similar_places():
    text = "def a():\n    x = 1\n\ndef b():\n    x = 1\n"
    with pytest.raises(AnchorError) as exc:
        anchors.locate(text, "def c():\n    x = 1", fuzzy=True, threshold=0.5)
    assert exc.value.kind is Match.AMBIGUOUS


def test_normalization_ignores_indentation_for_similarity_only():
    assert anchors._norm("  a  b  ") == anchors._norm("a b")


def test_fuzzy_span_maps_back_to_real_offsets():
    """The replacement must use real bytes, not normalized ones."""
    res = anchors.locate(SRC, "def alpha( ):\n  value = 1\n  return value", fuzzy=True)
    assert SRC[res.start : res.end].startswith("def alpha():")


def test_classify_never_raises():
    assert anchors.classify(SRC, "nothing here") is Match.NOT_FOUND
    assert anchors.classify(SRC, "    return value") is Match.AMBIGUOUS
    assert anchors.classify(SRC, "    value = 1") is Match.EXACT


def test_empty_anchor_finds_nothing():
    assert anchors.find_exact(SRC, "") == []
