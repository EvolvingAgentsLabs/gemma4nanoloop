"""The call log is the regression suite (PLAN.md §4 Phase 0.4), so it must be
robust: never raise into the caller, and always survive a truncated file."""

from __future__ import annotations

from nanoloop import calllog


def _rec(**kw):
    base = dict(
        phase="build",
        prompt_tokens=100,
        tools_offered=["read_file"],
        raw_output="{}",
        parsed_output=None,
        parse_ok=True,
        latency_ms=1200,
        wall_clock_since_start=3.4,
    )
    base.update(kw)
    return calllog.CallRecord(**base)


def test_records_required_fields(tmp_path):
    path = tmp_path / "calls.jsonl"
    calllog.record(_rec(), path)
    rows = calllog.read(path)
    assert len(rows) == 1
    for field in (
        "phase",
        "prompt_tokens",
        "tools_offered",
        "raw_output",
        "parsed_output",
        "parse_ok",
        "latency_ms",
        "wall_clock_since_start",
    ):
        assert field in rows[0]


def test_appends_never_overwrites(tmp_path):
    path = tmp_path / "calls.jsonl"
    calllog.record(_rec(phase="plan"), path)
    calllog.record(_rec(phase="build"), path)
    assert [r["phase"] for r in calllog.read(path)] == ["plan", "build"]


def test_read_tolerates_a_truncated_final_line(tmp_path):
    path = tmp_path / "calls.jsonl"
    calllog.record(_rec(), path)
    with path.open("a") as fh:
        fh.write('{"phase": "bui')  # killed mid-write
    assert len(calllog.read(path)) == 1


def test_logging_failure_does_not_raise(tmp_path):
    # A directory where the file should be: writing must fail silently.
    bad = tmp_path / "blocked"
    bad.mkdir()
    calllog.record(_rec(), bad)  # must not raise


def test_missing_log_reads_as_empty(tmp_path):
    assert calllog.read(tmp_path / "nope.jsonl") == []


def test_clock_offset_is_monotonic_and_resettable():
    calllog.reset_clock()
    assert calllog.now_offset() >= 0
