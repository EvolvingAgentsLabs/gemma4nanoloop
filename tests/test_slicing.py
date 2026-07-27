"""G2: the model can only anchor on text it was shown.

Head-truncation made every anchor past the limit unreachable, and the failure
surfaced as a repeated `not_found` — indistinguishable from "the model cannot
copy". Measured on crew.py: 36,041 chars, and run_goal / verify_plan /
run_check all sat beyond the old 12,000-char window.
"""

from __future__ import annotations

from nanoloop import crew
from nanoloop.crew import Step

BIG = (
    '"""Module."""\n\n'
    + "".join(f"def filler_{i}():\n    return {i}\n\n\n" for i in range(400))
    + "def target_at_the_very_end():\n    return 'needle'\n"
)


def _write(tmp_path, text=BIG):
    (tmp_path / "big.py").write_text(text)
    return tmp_path


def test_small_files_are_shown_whole(tmp_path):
    (tmp_path / "s.py").write_text("def a():\n    return 1\n")
    out = crew._read_slice(tmp_path, "s.py")
    assert out == "def a():\n    return 1\n"
    assert "omitted" not in out


def test_a_symbol_past_the_limit_becomes_reachable(tmp_path):
    _write(tmp_path)
    step = Step(title="update target_at_the_very_end", target_file="big.py", intent="i")
    out = crew._read_slice(tmp_path, "big.py", limit=4000, step=step)
    assert "def target_at_the_very_end():" in out
    assert len(out) < len(BIG)


def test_head_truncation_would_have_missed_it(tmp_path):
    """Pins the old behaviour as broken, so nobody reintroduces it."""
    assert "def target_at_the_very_end():" not in BIG[:4000]


def test_defines_is_used_as_the_strongest_hint(tmp_path):
    _write(tmp_path)
    step = Step(
        title="unrelated words",
        target_file="big.py",
        intent="nothing",
        defines="target_at_the_very_end",
    )
    out = crew._read_slice(tmp_path, "big.py", limit=4000, step=step)
    assert "def target_at_the_very_end():" in out


def test_omission_is_announced_so_the_model_sees_a_gap(tmp_path):
    _write(tmp_path)
    step = Step(title="target_at_the_very_end", target_file="big.py", intent="i")
    out = crew._read_slice(tmp_path, "big.py", limit=4000, step=step)
    assert "omitted" in out


def test_falls_back_to_head_and_tail_when_no_symbol_matches(tmp_path):
    """Appending is the most common step, and the tail is where you anchor."""
    _write(tmp_path)
    step = Step(title="zzz", target_file="big.py", intent="qqq")
    out = crew._read_slice(tmp_path, "big.py", limit=4000, step=step)
    assert "def filler_0():" in out  # head kept
    assert "def target_at_the_very_end():" in out  # tail kept too
    assert "omitted" in out


def test_slice_is_verbatim_so_anchors_still_match(tmp_path):
    """Every shown region must be byte-identical to the file, or a copied
    anchor matches nothing."""
    _write(tmp_path)
    step = Step(title="target_at_the_very_end", target_file="big.py", intent="i")
    out = crew._read_slice(tmp_path, "big.py", limit=4000, step=step)
    for chunk in out.split("\n["):
        body = chunk.split("...]\n")[-1].strip()
        if len(body) > 80:
            assert body[:80] in BIG


def test_a_syntax_error_does_not_break_slicing(tmp_path):
    (tmp_path / "bad.py").write_text("def (((:\n" + "x = 1\n" * 5000)
    step = Step(title="anything", target_file="bad.py", intent="i")
    out = crew._read_slice(tmp_path, "bad.py", limit=2000, step=step)
    assert "omitted" in out  # falls back cleanly


def test_non_python_files_use_head_and_tail(tmp_path):
    (tmp_path / "notes.md").write_text("START\n" + "x\n" * 5000 + "END\n")
    out = crew._read_slice(tmp_path, "notes.md", limit=1000)
    assert out.startswith("START") and out.rstrip().endswith("END")


def test_missing_file_is_reported(tmp_path):
    assert "does not exist" in crew._read_slice(tmp_path, "nope.py")


def test_symbol_span_finds_classes_too(tmp_path):
    text = "class Store:\n    def add(self):\n        pass\n"
    assert crew.symbol_span(text, ["Store"]) == (1, 3)


def test_needles_prefer_defines_then_title(tmp_path):
    step = Step(title="add by_tag to Store", target_file="x", intent="", defines="by_tag")
    assert crew._needles(step)[0] == "by_tag"


def test_short_identifiers_are_ignored_as_noise():
    step = Step(title="a b to the Store", target_file="x", intent="")
    assert all(len(n) > 2 for n in crew._needles(step))
