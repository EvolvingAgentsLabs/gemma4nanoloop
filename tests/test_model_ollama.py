"""Pins the two runtime facts that each cost real wall clock (PLAN.md §4 Phase 0).

1. num_ctx must reach the server. On the OpenAI path it belongs in top-level
   extra_body — inside model_kwargs LangChain drops it and Ollama then truncates
   history silently, which in an agent loop reads as the model forgetting.
2. Reasoning must be OFF. Gemma 4 is a reasoning model; measured, leaving it on
   costs 8x wall clock (222s vs 27s on the same prompt).
"""

from __future__ import annotations

import json

from nanoloop import model_ollama

# --- reasoning: the 8x finding ----------------------------------------------


def test_reasoning_is_off_by_default():
    """Measured: /api/chat think:false = 26.8s, vs 222.3s with reasoning on."""
    assert model_ollama.THINK is False


def test_native_body_carries_think_flag():
    body = model_ollama.build_native_body("m", "sys", "usr", 8192, 0.0, None)
    assert body["think"] is False
    assert body["stream"] is False


def test_native_body_puts_num_ctx_in_options():
    body = model_ollama.build_native_body("m", "sys", "usr", 4096, 0.2, None)
    assert body["options"]["num_ctx"] == 4096
    assert body["options"]["temperature"] == 0.2


def test_native_body_uses_the_format_field_for_schema():
    """PLAN.md §4 specifies `format = schema_of(...)` — native, and correct here."""
    schema = {"type": "object"}
    body = model_ollama.build_native_body("m", "s", "u", 2048, 0.0, schema)
    assert body["format"] == schema
    assert "response_format" not in body


def test_native_body_omits_format_when_no_schema():
    assert "format" not in model_ollama.build_native_body("m", "s", "u", 2048, 0.0, None)


# --- the OpenAI transport (LiteRT-LM) ---------------------------------------


def test_extra_body_carries_num_ctx_both_places():
    body = model_ollama.build_extra_body(8192)
    assert body["num_ctx"] == 8192
    assert body["options"]["num_ctx"] == 8192


def test_openai_structured_mode_uses_response_format(monkeypatch):
    """`format` is silently ignored on /v1; response_format is the equivalent."""
    monkeypatch.setattr(model_ollama, "STRUCTURED_MODE", "openai")
    body = model_ollama.build_extra_body(2048, {"type": "object"})
    assert body["response_format"]["type"] == "json_schema"
    assert "format" not in body


def test_native_structured_mode_uses_format(monkeypatch):
    monkeypatch.setattr(model_ollama, "STRUCTURED_MODE", "native")
    body = model_ollama.build_extra_body(2048, {"type": "object"})
    assert body["format"] == {"type": "object"}


def test_no_schema_means_no_format_key():
    assert "format" not in model_ollama.build_extra_body(2048)


# --- transport selection -----------------------------------------------------


def test_ollama_defaults_to_the_native_transport():
    assert model_ollama.BACKEND == "ollama"
    assert model_ollama.BACKENDS["ollama"][0].endswith(":11434")


def test_litert_backend_is_configured():
    assert model_ollama.BACKENDS["litert"][1] == "gemma4-12b,gpu"
    assert model_ollama.BACKENDS["litert"][0].endswith(":9379")


# --- empty content must raise, not return "" ---------------------------------


def test_empty_content_raises_with_a_diagnostic(monkeypatch):
    """Empty content + reasoning is the documented failure. It must not look
    like a successful empty answer."""

    def fake(system, user, num_ctx, temperature, schema):
        return "", {"input_tokens": 10, "output_tokens": 3562}, "x" * 6249

    monkeypatch.setattr(model_ollama, "_call_native", fake)
    monkeypatch.setattr(model_ollama, "BACKEND", "ollama")
    try:
        model_ollama.chat("s", "u", phase="build")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "empty content" in str(e)
        assert "6249" in str(e)


def test_successful_call_returns_content(monkeypatch, tmp_path):
    from nanoloop import calllog

    monkeypatch.setattr(calllog, "LOG_PATH", tmp_path / "c.jsonl")
    monkeypatch.setattr(
        model_ollama,
        "_call_native",
        lambda *a: ('{"ok": 1}', {"input_tokens": 5, "output_tokens": 7}, ""),
    )
    monkeypatch.setattr(model_ollama, "BACKEND", "ollama")
    assert model_ollama.chat("s", "u", phase="build") == '{"ok": 1}'
    rows = calllog.read(tmp_path / "c.jsonl")
    assert rows[0]["thinking_chars"] == 0
    assert rows[0]["prompt_tokens"] == 5


# --- aistudio backend (measurement oracle) ----------------------------------


def test_aistudio_model_and_endpoint():
    base, model = model_ollama.BACKENDS["aistudio"]
    assert model == "gemma-4-26b-a4b-it"
    assert base.endswith("/v1beta/openai")


def test_system_role_is_folded_for_aistudio(monkeypatch):
    """Gemma via the Gemini API rejects a system role. Folding keeps ONE prompt
    definition across backends, so an oracle comparison stays apples-to-apples."""
    monkeypatch.setattr(model_ollama, "BACKEND", "aistudio")
    msgs = model_ollama.build_messages("SYS", "USR")
    assert [m["role"] for m in msgs] == ["user"]
    assert "SYS" in msgs[0]["content"] and "USR" in msgs[0]["content"]


def test_system_role_is_kept_for_local_backends(monkeypatch):
    monkeypatch.setattr(model_ollama, "BACKEND", "ollama")
    assert [m["role"] for m in model_ollama.build_messages("S", "U")] == ["system", "user"]


def test_api_key_is_read_from_any_accepted_var(monkeypatch):
    monkeypatch.setattr(model_ollama, "BACKEND", "aistudio")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "k123")
    assert model_ollama.api_key() == "k123"


def test_local_backends_need_no_key(monkeypatch):
    monkeypatch.setattr(model_ollama, "BACKEND", "ollama")
    assert model_ollama.api_key() is None


def test_probe_reports_a_missing_key_rather_than_failing_obscurely(monkeypatch):
    monkeypatch.setattr(model_ollama, "BACKEND", "aistudio")
    for v in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AISTUDIO_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    out = model_ollama.probe()
    assert out["ok"] is False and "no API key" in out["error"]


# --- inline <thought>: the third shape of the reasoning problem --------------


def test_inline_thought_is_stripped_from_the_answer():
    """aistudio returns `<thought>...</thought>ok`. Left in place, every
    structured-output parse fails because the JSON does not start at char 0."""
    answer, thought = model_ollama.split_thought("<thought>reasoning here</thought>ok")
    assert answer == "ok"
    assert "reasoning here" in thought


def test_inline_thought_before_json():
    raw = '<thought>I should return JSON</thought>{"path": "a.py"}'
    answer, _ = model_ollama.split_thought(raw)
    assert answer.startswith("{") and json.loads(answer)["path"] == "a.py"


def test_multiple_thought_blocks_all_removed():
    answer, thought = model_ollama.split_thought("<thought>a</thought>X<thought>b</thought>Y")
    assert answer == "XY"
    assert "a" in thought and "b" in thought


def test_text_without_thought_is_untouched():
    assert model_ollama.split_thought('{"ok": 1}') == ('{"ok": 1}', "")


def test_unclosed_thought_yields_no_false_answer():
    """Truncated mid-thought: nothing after the open tag is usable, so the
    answer must come back empty rather than as garbage reasoning text."""
    answer, thought = model_ollama.split_thought("<thought>cut off here")
    assert answer == ""
    assert "cut off" in thought


def test_reasoning_effort_omitted_by_default():
    """gemma-4-26b-a4b-it returns HTTP 400 if reasoning_effort is sent at all."""
    assert model_ollama.REASONING_EFFORT == ""
