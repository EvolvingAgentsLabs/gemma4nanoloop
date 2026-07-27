"""Model client for local Gemma 4 12B.

TWO TRANSPORTS, AND THE CHOICE IS WORTH 8x WALL CLOCK.

    ollama   POST /api/chat   native  — think:false + format   DEFAULT
    litert   POST /v1/chat/completions  OpenAI-compatible

Measured 2026-07-26, Ollama 0.31.2, gemma4:12b, same prompt (see PLAN.md §4
Phase 0, IMPLEMENTATION.md §4):

    /v1      + think:false   222.3s   139 content tokens, 6,249 chars of REASONING
    /api/chat + think:false   26.8s   164 content tokens,     0 chars of reasoning

Gemma 4 is a REASONING model. Ollama returns chain-of-thought in a separate
field (`message.thinking` natively, `message.reasoning` on /v1) and leaves
`content` EMPTY until thinking completes. Two consequences that cost a day if
you meet them without warning:

  1. Reading only `.content` yields an empty string while the model burns
     thousands of tokens. With a token cap you get `finish_reason=length` and
     nothing at all — it reads as a broken model, not as unrequested reasoning.
  2. `/v1` IGNORES `think: false`. Only the native endpoint honours it.

PLAN.md's cost model ("a 300-token edit is 15-20s") holds only with reasoning
OFF. Leaving it on adds thousands of tokens to EVERY call — fatal on a fanless
Air. Set THINK=True deliberately and re-measure; never by accident.

STRUCTURED OUTPUT. PLAN.md §4 specifies `format = schema_of(...)`, which is the
native field — correct, and it works here. It is silently ignored on /v1, where
the equivalent is `response_format`. Both are implemented; the transport picks.

THE num_ctx DETAIL (PLAN.md §1) survives in both: natively it goes in `options`,
and on the OpenAI path it must be top-level `extra_body` — inside `model_kwargs`
LangChain warns and drops it, and Ollama then truncates history silently.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from . import budget as budget_mod
from . import calllog

try:  # .env is gitignored; the AI Studio key lives there, never in the repo.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# base_url, default model. `aistudio` is Google's OpenAI-compatible shim, used as
# a measurement ORACLE rather than a development runtime — see ORACLE below.
BACKENDS = {
    "ollama": ("http://localhost:11434", "gemma4:12b"),
    "litert": ("http://localhost:9379", "gemma4-12b,gpu"),
    "aistudio": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemma-4-26b-a4b-it"),
}

# Backends that need a bearer token, and where to find it.
API_KEY_ENV = {"aistudio": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AISTUDIO_API_KEY")}

# Gemma served through the Gemini API has historically REJECTED a system role
# outright (400, "system instruction is not supported"). Folding the system
# prompt into the user turn keeps one prompt definition across every backend —
# without this you end up maintaining two prompt variants and the comparison
# stops being apples-to-apples.
FOLD_SYSTEM = {"aistudio"}

BACKEND = os.environ.get("NANOLOOP_BACKEND", "ollama")

# Reasoning off by default. See the 8x measurement above.
THINK = os.environ.get("NANOLOOP_THINK", "0").lower() in ("1", "true", "yes")

# Hosted backends only, and empty by default: gemma-4-26b-a4b-it returns HTTP 400
# ("Thinking budget is not supported for this model") if reasoning_effort is sent
# at all. Set to none|low|medium|high for a model that does accept it.
REASONING_EFFORT = os.environ.get("NANOLOOP_REASONING_EFFORT", "")

# On /v1 only: `native` is silently ignored there, so the default is `openai`.
STRUCTURED_MODE = os.environ.get("NANOLOOP_STRUCTURED_MODE", "openai")

DEFAULT_NUM_CTX = 8192
DEFAULT_TIMEOUT = int(os.environ.get("NANOLOOP_TIMEOUT", "900"))

# Hard cap on generated tokens. One anchor edit or one small module is a few
# hundred tokens; nothing legitimate approaches this.
#
# Without it a degenerate sample runs to the model's own ceiling: observed
# out=32768 on an Edit, 696.7s of wall clock for output that could never parse.
# Capped, the same failure returns truncated JSON in seconds and the repair loop
# gets its turn. Fail fast beats fail expensive.
MAX_OUTPUT_TOKENS = int(os.environ.get("NANOLOOP_MAX_OUTPUT_TOKENS", "4096"))

# The plan is the longest legitimate output (N steps + acceptance criteria) AND
# on this model the <thought> block is billed against the SAME output budget —
# a `max_tokens: 50` probe spent all 50 tokens thinking and returned
# `finish_reason: length` with empty content. Google reports
# `completion_tokens: 0` for those tokens, so the squeeze is invisible in usage.
# Too small a cap therefore looks like "the backend returns nothing" rather than
# "you throttled it". Still far below the 32768 runaway this guards against.
PHASE_MAX_TOKENS = {"plan": 8192}


def max_tokens_for(phase: str) -> int:
    return PHASE_MAX_TOKENS.get(phase, MAX_OUTPUT_TOKENS)


def _endpoint() -> tuple[str, str]:
    base, model = BACKENDS.get(BACKEND, BACKENDS["ollama"])
    return os.environ.get("NANOLOOP_BASE_URL", base), os.environ.get("NANOLOOP_MODEL", model)


def build_native_body(
    model: str,
    system: str,
    user: str,
    num_ctx: int,
    temperature: float,
    schema: dict | None,
    phase: str = "",
) -> dict[str, Any]:
    """Body for Ollama's native /api/chat. Pure, so a test can assert on it."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "think": THINK,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": max_tokens_for(phase),
        },
    }
    if schema is not None:
        body["format"] = schema
    return body


def build_extra_body(num_ctx: int, schema: dict | None = None) -> dict[str, Any]:
    """Top-level extra_body for the OpenAI-compatible transport (LiteRT-LM).

    num_ctx goes in twice on purpose: some shims read `options.num_ctx`, others a
    bare top-level `num_ctx`. Sending both costs nothing and removes a whole
    class of silent-truncation bug. Neither location is `model_kwargs`.
    """
    body: dict[str, Any] = {"num_ctx": num_ctx, "options": {"num_ctx": num_ctx}}
    if schema is not None:
        if STRUCTURED_MODE == "openai":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": schema, "strict": True},
            }
        else:
            body["format"] = schema
    return body


def api_key() -> str | None:
    """Bearer token for the active backend, if it needs one."""
    for var in API_KEY_ENV.get(BACKEND, ()):
        val = os.environ.get(var)
        if val:
            return val
    return None


def _post(url: str, body: dict, timeout: int, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # The body carries the actual reason (bad model name, system role
        # unsupported, quota). Without it you get a bare "400" and no lead.
        detail = e.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from e


def _call_native(
    system: str,
    user: str,
    num_ctx: int,
    temperature: float,
    schema: dict | None,
    phase: str = "",
) -> tuple[str, dict, str]:
    base, model = _endpoint()
    body = build_native_body(model, system, user, num_ctx, temperature, schema, phase)
    data = _post(f"{base}/api/chat", body, DEFAULT_TIMEOUT)
    msg = data.get("message", {}) or {}
    usage = {"input_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")}
    return msg.get("content") or "", usage, msg.get("thinking") or ""


THOUGHT_RE = re.compile(r"<thought>.*?</thought>", re.DOTALL)


def split_thought(text: str) -> tuple[str, str]:
    """Separate inline <thought> blocks from the real answer.

    A THIRD shape for the same problem, and the nastiest of the three:

        ollama /api/chat   separate `thinking` field   controllable via think:false
        ollama /v1         separate `reasoning` field  NOT controllable
        aistudio           INLINE <thought>...</thought> IN THE CONTENT

    gemma-4-26b-a4b-it rejects reasoning_effort outright, so the reasoning cannot
    be turned off — it can only be stripped after the fact. Left in place every
    structured-output parse fails, because the JSON does not start at character
    zero. Observed: `<thought>...</thought>ok` for a prompt asking for one word.

    Returns (answer, thought) so the thought length still reaches the call log
    and stays comparable with the other two backends.
    """
    thoughts = THOUGHT_RE.findall(text)
    answer = THOUGHT_RE.sub("", text).strip()
    if not thoughts and "<thought>" in text:
        # Truncated mid-thought: no closing tag, so nothing after it is usable.
        head, _, tail = text.partition("<thought>")
        return head.strip(), tail
    return answer, "".join(thoughts)


def build_messages(system: str, user: str) -> list[dict]:
    """Chat messages, folding the system turn where the backend rejects it."""
    if BACKEND in FOLD_SYSTEM:
        return [{"role": "user", "content": f"{system}\n\n{user}"}]
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _call_openai(
    system: str,
    user: str,
    num_ctx: int,
    temperature: float,
    schema: dict | None,
    phase: str = "",
) -> tuple[str, dict, str]:
    base, model = _endpoint()
    remote = BACKEND in API_KEY_ENV
    body: dict[str, Any] = {
        "model": model,
        "messages": build_messages(system, user),
        "temperature": temperature,
        "max_tokens": max_tokens_for(phase),
    }
    if remote:
        # A hosted endpoint has no num_ctx knob — that is a local-runtime concept.
        #
        # reasoning_effort is sent ONLY when explicitly requested. gemma-4-26b-a4b-it
        # rejects it outright ("Thinking budget is not supported for this model",
        # HTTP 400) even though the native SDK exposes thinking_level — the OpenAI
        # shim does not map it for this model. Sending it unconditionally makes
        # every call fail. Whether the model reasons anyway is measured, not
        # assumed: `thinking_chars` in the call log is the check.
        if REASONING_EFFORT:
            body["reasoning_effort"] = REASONING_EFFORT
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": schema, "strict": True},
            }
    else:
        body.update(build_extra_body(num_ctx, schema))

    key = api_key()
    headers = {"Authorization": f"Bearer {key}"} if key else None
    data = _post(
        f"{base}/chat/completions" if remote else f"{base}/v1/chat/completions",
        body,
        DEFAULT_TIMEOUT,
        headers,
    )
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {}) or {}
    u = data.get("usage", {}) or {}
    usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning") or ""
    if "<thought>" in content:  # aistudio inlines it; see split_thought()
        content, inline = split_thought(content)
        reasoning = reasoning + inline
    return content, usage, reasoning


def chat(
    system: str,
    user: str,
    *,
    phase: str,
    num_ctx: int = DEFAULT_NUM_CTX,
    temperature: float = 0.0,
    schema: dict | None = None,
    tools_offered: list[str] | None = None,
    step_index: int | None = None,
    attempt: int | None = None,
) -> str:
    """One model call. Always logged, even when it fails.

    Returns raw assistant text; parsing is the caller's job. Reasoning length is
    logged separately — if it is ever non-zero unexpectedly, that alone explains
    a latency regression.
    """
    # Before the call, never after: starting work the budget cannot cover
    # wastes the most expensive thing in the loop. Raises BudgetExhausted,
    # which the crew turns into a reported outcome rather than a crash.
    budget_mod.check()

    _, model_name = _endpoint()
    caller = _call_native if BACKEND == "ollama" else _call_openai

    t0 = time.monotonic()
    raw, thinking, err = "", "", None
    usage: dict[str, Any] = {}
    try:
        raw, usage, thinking = caller(system, user, num_ctx, temperature, schema, phase)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as e:
        err = f"{type(e).__name__}: {e}"
    latency_ms = int((time.monotonic() - t0) * 1000)
    budget_mod.spend((usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0))

    calllog.record(
        calllog.CallRecord(
            phase=phase,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            tools_offered=tools_offered or [],
            raw_output=raw,
            parsed_output=None,
            parse_ok=False,
            latency_ms=latency_ms,
            wall_clock_since_start=calllog.now_offset(),
            model=model_name,
            num_ctx=num_ctx,
            temperature=temperature,
            step_index=step_index,
            attempt=attempt,
            error=err,
            thinking_chars=len(thinking),
        )
    )
    if err:
        raise RuntimeError(err)
    if not raw:
        # Empty content with reasoning present is the failure documented above.
        raise RuntimeError(
            f"model returned empty content ({len(thinking)} chars of reasoning, "
            f"cap {max_tokens_for(phase)}). Reasoning shares the output budget, "
            f"so a tight cap starves the answer. "
            f"If reasoning is non-zero, THINK is on — see nanoloop/model_ollama.py."
        )
    return raw


def probe() -> dict[str, Any]:
    """Phase 0 liveness check: does this endpoint answer at all?"""
    base_url, model = _endpoint()
    if BACKEND in API_KEY_ENV and not api_key():
        return {
            "backend": BACKEND,
            "base_url": base_url,
            "model": model,
            "ok": False,
            "error": f"no API key; set one of {API_KEY_ENV[BACKEND]} (e.g. in .env)",
        }
    t0 = time.monotonic()
    try:
        out = chat("Reply with the single word: ok.", "ping", phase="probe", num_ctx=512)
        return {
            "backend": BACKEND,
            "base_url": base_url,
            "model": model,
            "think": THINK,
            "ok": True,
            "reply": out.strip()[:40],
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "backend": BACKEND,
            "base_url": base_url,
            "model": model,
            "think": THINK,
            "ok": False,
            "error": str(e)[:200],
        }
