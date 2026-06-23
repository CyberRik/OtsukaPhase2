"""OpenAI client + tool-calling loop for exp3 — ported from demo/app.py.

Keeps the demo's proven behaviour: native OpenAI `tool_calls` with a safe
`_parse_xlam` fallback for the XLAM-style text the model sometimes emits. The
tool loop is factored into `stream_turn` (used by the Gradio chat) and a thin
`simple_complete` (used by narration). Network/parse failures are surfaced as
strings or raised for the caller to fall back on — nothing here crashes the app.
"""
from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator

from openai import OpenAI

from senpai import config
from senpai.tools.impl import dispatch
from senpai.tools.schemas import TOOLS

# A single OpenAI-compatible client. `timeout`/`max_retries` keep a slow or down
# inference server (vLLM/ollama) from hanging the API — callers fall back to the
# deterministic render on any error.
client = OpenAI(
    base_url=config.BASE_URL,
    api_key="dummy",
    timeout=config.LLM_TIMEOUT,
    max_retries=0,
)

fallback_client = OpenAI(
    base_url=config.FALLBACK_BASE_URL,
    api_key="dummy",
    timeout=config.LLM_TIMEOUT,
    max_retries=0,
)


def _parse_xlam(content: str | None):
    """exp3 sometimes emits XLAM-style `[func(a=1, b='x'), ...]` as plain text
    instead of OpenAI tool_calls. Parse it safely with `ast` (literal args only,
    never code). Returns a list of (name, args_dict) or None."""
    if not content:
        return None
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip().strip("`")
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        node = ast.parse(text[start:end + 1], mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.List):
        return None
    calls = []
    for el in node.elts:
        if isinstance(el, ast.Call) and isinstance(el.func, ast.Name):
            try:
                kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in el.keywords}
            except (ValueError, SyntaxError):
                continue
            calls.append((el.func.id, kwargs))
    return calls or None


# Prefilling the assistant turn with an already-closed, empty think block makes
# the reasoning distill skip its <think> phase and answer immediately. This is
# the only lever that works on the current llama-server build — the model's chat
# template has no `enable_thinking` var and ignores `reasoning_effort`/`/no_think`.
# Cutting the (long) reasoning phase is the dominant latency win for short
# conversational outputs like Senior Commentary.
_NO_THINK_PREFILL = {"role": "assistant", "content": "<think>\n\n</think>\n\n"}


def _prep(messages: list[dict], no_think: bool) -> list[dict]:
    return [*messages, _NO_THINK_PREFILL] if no_think else messages


def simple_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None, *, no_think: bool = False,
                    allow_fallback: bool = True) -> str:
    """One plain completion, no tools. Raises on transport error so callers
    (e.g. narration) can fall back to a templated string. Strips any
    `<think>...</think>` reasoning span (the served model is a reasoning
    distill) so callers get only the final coaching text. `no_think` disables the
    reasoning phase (low latency); `allow_fallback=False` pins the request to the
    primary endpoint and re-raises instead of silently switching models."""
    msgs = _prep(messages, no_think)
    try:
        resp = client.chat.completions.create(
            model=config.MODEL, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
        )
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Primary server failed ({e}). Trying fallback...")
        resp = fallback_client.chat.completions.create(
            model=config.FALLBACK_MODEL, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
        )
    content = resp.choices[0].message.content or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    return content.strip()


def _delta_reasoning(delta) -> str | None:
    """Some OpenAI-compatible servers (llama.cpp's llama-server, DeepSeek, vLLM
    with `--reasoning-parser`) split chain-of-thought into a separate
    `reasoning_content` field and leave `content`/`delta.content` empty until the
    answer begins. The openai SDK exposes such non-standard fields on
    `model_extra`; older builds attach them directly. Check both."""
    rc = getattr(delta, "reasoning_content", None)
    if rc is None:
        extra = getattr(delta, "model_extra", None)
        if extra:
            rc = extra.get("reasoning_content")
    return rc


def stream_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None, *, no_think: bool = False,
                    allow_fallback: bool = True) -> Iterator[str]:
    """Stream a completion token-by-token from the OpenAI-compatible server.
    Yields a `<think>…</think>` reasoning span (when the backend emits one)
    followed by the answer deltas — a single text stream callers can split on
    `</think>`. Backends that inline `<think>` in `content` (vLLM/ollama) flow
    straight through unchanged; backends that put reasoning in a separate
    `reasoning_content` field (llama.cpp) are reconstructed into the same shape,
    so the thinking phase stays visible instead of streaming nothing.
    `no_think` disables reasoning for low latency; `allow_fallback=False` pins the
    request to the primary endpoint and re-raises instead of switching models.
    Raises on transport error so callers can fall back."""
    msgs = _prep(messages, no_think)
    try:
        stream = client.chat.completions.create(
            model=config.MODEL, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
        )
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Primary server failed ({e}). Trying fallback stream...")
        stream = fallback_client.chat.completions.create(
            model=config.FALLBACK_MODEL, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
        )
    think_open = think_closed = False
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if not delta:
            continue
        reasoning = _delta_reasoning(delta)
        if reasoning:
            if not think_open:
                think_open = True
                yield "<think>"
            yield reasoning
        if delta.content:
            if think_open and not think_closed:
                think_closed = True
                yield "</think>"
            yield delta.content


def stream_turn(convo: list[dict], tools: list[dict] | None = None):
    """Generator driving one user turn through the tool loop. Yields
    (tool_log, answer_or_None) after each round; the final yield has the answer.
    `convo` is mutated in place with assistant/tool messages (demo semantics).
    `tools` selects which tool schemas the model may call (defaults to all TOOLS);
    each front end passes its own role-scoped subset."""
    tools = tools if tools is not None else TOOLS
    tool_log: list[tuple[str, str, str]] = []
    answer = None
    for _ in range(config.MAX_TOOL_ROUNDS):
        try:
            resp = client.chat.completions.create(
                model=config.MODEL, messages=convo, tools=tools,
                tool_choice="auto", temperature=0.0,
            )
        except Exception as e:
            print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
            try:
                resp = fallback_client.chat.completions.create(
                    model=config.FALLBACK_MODEL, messages=convo, tools=tools,
                    tool_choice="auto", temperature=0.0,
                )
            except Exception as fe:
                answer = f"⚠️ サーバーエラー: {e} (Fallback: {fe})"
                break

        msg = resp.choices[0].message
        if msg.tool_calls:
            calls = [(tc.id, tc.function.name, tc.function.arguments)
                     for tc in msg.tool_calls]
        else:
            parsed = _parse_xlam(msg.content)
            calls = [(f"call_{len(tool_log) + i}", name, json.dumps(args))
                     for i, (name, args) in enumerate(parsed)] if parsed else []

        if not calls:
            answer = (msg.content or "").strip() or "(no response)"
            break

        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": args}}
            for cid, name, args in calls]})
        for cid, name, args in calls:
            result = dispatch(name, args)
            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})
        yield tool_log, None
    else:
        answer = answer or "⚠️ ツール呼び出しの上限に達しました。"
    yield tool_log, answer


def stream_chat_turn(convo: list[dict], tools: list[dict] | None = None):
    """Web-facing tool loop that *streams the final answer* token-by-token.

    Same loop as `stream_turn` (kept intact for the Gradio apps), but instead of
    a single blocking final completion it streams the answering round so the web
    Assistant feels as live as Review Coach. Yields typed event dicts:
      {"type": "tool", "name", "args", "result"}   — one per executed tool
      {"type": "delta", "text"}                     — answer tokens as they arrive
      {"type": "answer", "text"}                    — the full answer (terminal)
    `convo` is mutated in place (demo semantics). Reasoning (`<think>…</think>`)
    is stripped so only the user-facing answer streams."""
    tools = tools if tools is not None else TOOLS
    tool_log: list[tuple[str, str, str]] = []
    from senpai.retrieval import trace as _trace
    _trace.start()  # begin a retrieval trace for this turn (Retrieval Explorer)

    # Tool-selection rounds also skip the <think> phase when enabled — this is
    # where the bulk of the latency lives (the synthesis round alone is not enough).
    sel_msgs = lambda: _prep(convo, config.TOOLLOOP_NO_THINK)
    for round_i in range(config.MAX_TOOL_ROUNDS):
        last_round = round_i == config.MAX_TOOL_ROUNDS - 1
        try:
            resp = client.chat.completions.create(
                model=config.MODEL, messages=sel_msgs(), tools=tools,
                tool_choice="auto", temperature=0.0,
            )
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
            try:
                resp = fallback_client.chat.completions.create(
                    model=config.FALLBACK_MODEL, messages=sel_msgs(), tools=tools,
                    tool_choice="auto", temperature=0.0,
                )
            except Exception as fe:  # noqa: BLE001
                yield {"type": "answer", "text": f"⚠️ サーバーエラー: {e} (Fallback: {fe})"}
                return

        msg = resp.choices[0].message
        if msg.tool_calls:
            calls = [(tc.id, tc.function.name, tc.function.arguments)
                     for tc in msg.tool_calls]
        else:
            parsed = _parse_xlam(msg.content)
            calls = [(f"call_{len(tool_log) + i}", name, json.dumps(args))
                     for i, (name, args) in enumerate(parsed)] if parsed else []

        # No tool calls → this is the answering round. Re-run it as a stream so
        # the answer flows token-by-token instead of arriving all at once.
        if not calls:
            yield from _stream_final_answer(convo, tools, no_think=config.TOOLLOOP_NO_THINK)
            return

        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": args}}
            for cid, name, args in calls]})
        for cid, name, args in calls:
            result = dispatch(name, args)
            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})
            ev = {"type": "tool", "name": name, "args": _fmt_args(args), "result": result}
            retrieval = _trace.drain()  # any chunks this tool retrieved (Explorer)
            if retrieval:
                ev["retrieval"] = retrieval
            yield ev

        if last_round:
            # Hit the tool budget — force a final answer from what we have.
            yield from _stream_final_answer(convo, tools, no_think=config.TOOLLOOP_NO_THINK)
            return


def _stream_final_answer(convo: list[dict], tools: list[dict] | None, *, no_think: bool = False):
    """Stream one tool-free completion as the answer, stripping any reasoning.
    Emits `delta` events live and a terminal `answer` with the full text.
    `no_think` prefills an empty think block so the reasoning distill skips its
    <think> phase and answers immediately (the dominant latency win)."""
    full, emitted = "", 0
    msgs = _prep(convo, no_think)
    try:
        stream = client.chat.completions.create(
            model=config.MODEL, messages=msgs, temperature=0.0,
            max_tokens=config.LLM_MAX_TOKENS, stream=True,
        )
    except Exception:  # noqa: BLE001 — fall back to a single blocking answer
        try:
            resp = fallback_client.chat.completions.create(
                model=config.FALLBACK_MODEL, messages=msgs, temperature=0.0,
                max_tokens=config.LLM_MAX_TOKENS,
            )
            text = re.sub(r"<think>.*?</think>", "",
                          resp.choices[0].message.content or "", flags=re.DOTALL).strip()
            yield {"type": "answer", "text": text or "(no response)"}
        except Exception as fe:  # noqa: BLE001
            yield {"type": "answer", "text": f"⚠️ サーバーエラー: {fe}"}
        return

    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None) if delta else None
        if not piece:
            continue
        full += piece
        # Strip any echoed reasoning span; only stream what follows it.
        if "</think>" in full:
            answer = full.split("</think>", 1)[1].lstrip("\n ")
        elif "<think>" in full:
            answer = ""
        else:
            answer = full
        new = answer[emitted:]
        if new:
            emitted += len(new)
            yield {"type": "delta", "text": new}

    final = re.sub(r"<think>.*?</think>", "", full, flags=re.DOTALL).strip()
    yield {"type": "answer", "text": final or "(no response)"}


def _fmt_args(arguments) -> str:
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return ", ".join(f"{k}={v!r}" for k, v in d.items())
    except Exception:
        return str(arguments)
