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


def simple_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None) -> str:
    """One plain completion, no tools. Raises on transport error so callers
    (e.g. narration) can fall back to a templated string. Strips any
    `<think>...</think>` reasoning span (the served model is a reasoning
    distill) so callers get only the final coaching text."""
    resp = client.chat.completions.create(
        model=config.MODEL, messages=messages, temperature=temperature,
        max_tokens=max_tokens or config.LLM_MAX_TOKENS,
    )
    content = resp.choices[0].message.content or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    return content.strip()


def stream_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None) -> Iterator[str]:
    """Stream a completion token-by-token from the OpenAI-compatible server
    (vLLM supports SSE streaming natively). Yields raw content deltas, including
    any `<think>` reasoning — callers decide how to present the thinking phase.
    Raises on transport error so callers can fall back."""
    stream = client.chat.completions.create(
        model=config.MODEL, messages=messages, temperature=temperature,
        max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
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
        except Exception as e:  # noqa: BLE001
            answer = f"⚠️ サーバーエラー: {e}"
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


def _fmt_args(arguments) -> str:
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return ", ".join(f"{k}={v!r}" for k, v in d.items())
    except Exception:
        return str(arguments)
