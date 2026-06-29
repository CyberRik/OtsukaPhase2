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
from senpai.orchestration.scheduler import AdaptiveScheduler, ToolCall as SchedToolCall
from senpai.orchestration.engine import ExecutionEngine
from senpai.agent.capabilities import build_registry

_SCHEDULER = AdaptiveScheduler()
_ENGINE = ExecutionEngine(build_registry())
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


def _synth_route(no_think: bool):
    """Hybrid model-decomposition router for the *final synthesis* round only.

    FAST (no_think) synthesis → the smaller FALLBACK model (8B Q4); THINK synthesis
    → the primary (27B), whose mentorship narrative we keep. Gated by
    `config.FAST_SYNTH_FALLBACK` (OFF by default, so the live path is unchanged —
    everything stays on the 27B). Tool *selection* never calls this; it is always
    the primary. Returns (synthesis_client, model_id, alt_client, alt_model) where
    `alt_*` is the other endpoint to fail over to. The Fast/Think decision itself
    stays with the existing reasoning router — this only picks who writes the
    already-decided FAST answer."""
    # SYNTH_ALL_FALLBACK: route ALL synthesis (FAST + THINK) to the 8B — latency
    # over accuracy. Otherwise the FAST→8B / THINK→27B hybrid.
    if config.SYNTH_ALL_FALLBACK or (no_think and config.FAST_SYNTH_FALLBACK):
        return fallback_client, config.FALLBACK_MODEL, client, config.MODEL
    return client, config.MODEL, fallback_client, config.FALLBACK_MODEL


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


# Atlas (spark) controls reasoning via the chat template's `enable_thinking`
# kwarg, surfaced to the OpenAI SDK through extra_body→chat_template_kwargs.
# (The old empty-<think> assistant prefill — the only lever on the previous
# llama-server build — is a NO-OP on atlas: it still emits a <think> phase.)
# Atlas also requires explicit sampling: with none it decodes greedily and
# degenerates into repetition loops on long output. `_gen_kwargs` carries both
# into every create() call; `no_think=True` disables the reasoning phase.
def _gen_kwargs(no_think: bool) -> dict:
    return {
        "top_p": config.LLM_TOP_P,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": not no_think},
            "top_k": config.LLM_TOP_K,
        },
    }


def _prep(messages: list[dict], no_think: bool) -> list[dict]:
    # Reasoning is now toggled via _gen_kwargs(enable_thinking); the messages
    # pass through unchanged (the empty-<think> prefill did nothing on atlas).
    return messages


def simple_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None, *, no_think: bool = False,
                    allow_fallback: bool = True, fast_decomp: bool = False) -> str:
    """One plain completion, no tools. Raises on transport error so callers
    (e.g. narration) can fall back to a templated string. Strips any
    `<think>...</think>` reasoning span (the served model is a reasoning
    distill) so callers get only the final coaching text. `no_think` disables the
    reasoning phase (low latency); `allow_fallback=False` pins the request to the
    primary endpoint and re-raises instead of silently switching models."""
    msgs = _prep(messages, no_think)
    primary_c, primary_m, alt_c, alt_m = (
        _synth_route(no_think) if fast_decomp else (client, config.MODEL, fallback_client, config.FALLBACK_MODEL))
    try:
        resp = primary_c.chat.completions.create(
            model=primary_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
        )
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Primary server {primary_m} failed ({e}). Trying fallback...")
        resp = alt_c.chat.completions.create(
            model=alt_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
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
                    allow_fallback: bool = True, fast_decomp: bool = False) -> Iterator[str]:
    """Stream a completion token-by-token from the OpenAI-compatible server.
    Yields a `<think>…</think>` reasoning span (when the backend emits one)
    followed by the answer deltas — a single text stream callers can split on
    `</think>`. Backends that inline `<think>` in `content` (vLLM/ollama) flow
    straight through unchanged; backends that put reasoning in a separate
    `reasoning_content` field (llama.cpp) are reconstructed into the same shape,
    so the thinking phase stays visible instead of streaming nothing.
    `no_think` disables reasoning for low latency; `allow_fallback=False` pins the
    request to the primary endpoint and re-raises instead of switching models.
    `fast_decomp=True` opts this call into the hybrid synthesis route (FAST → 8B)
    when `config.FAST_SYNTH_FALLBACK` is on — used by FAST grounded summaries
    (e.g. /research), not by narration. Raises on transport error so callers can
    fall back."""
    msgs = _prep(messages, no_think)
    primary_c, primary_m, alt_c, alt_m = (
        _synth_route(no_think) if fast_decomp else (client, config.MODEL, fallback_client, config.FALLBACK_MODEL))
    try:
        stream = primary_c.chat.completions.create(
            model=primary_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
            **_gen_kwargs(no_think),
        )
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Synthesis server {primary_m} failed ({e}). Trying {alt_m}...")
        stream = alt_c.chat.completions.create(
            model=alt_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
            **_gen_kwargs(no_think),
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
                tool_choice="auto", temperature=0.0, **_gen_kwargs(True),
            )
        except Exception as e:
            print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
            try:
                resp = fallback_client.chat.completions.create(
                    model=config.FALLBACK_MODEL, messages=convo, tools=tools,
                    tool_choice="auto", temperature=0.0, **_gen_kwargs(True),
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
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in {"schedule_meeting", "create_quote", "send_email"} or last_name.startswith("generate_"):
                    answer = last_result
                    break
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
        if tool_log:
            last_name, _, last_result = tool_log[-1]
            if last_name in {"schedule_meeting", "create_quote", "send_email"} or last_name.startswith("generate_"):
                answer = last_result
        answer = answer or "⚠️ ツール呼び出しの上限に達しました。"
    yield tool_log, answer


def _route_final_answer(convo, tools, tool_log, role):
    """Decide FAST vs REASONING for the synthesis round via the ReasoningRouter,
    emit a `routing` event (observability), then stream the answer. Tool-selection
    stays fast regardless; only this round is dynamically routed. When the router
    is "off" we fall back to the static TOOLLOOP_NO_THINK behaviour."""
    no_think = config.TOOLLOOP_NO_THINK
    if config.REASONING_ROUTER and config.REASONING_ROUTER != "off":
        try:
            from senpai.llm.routing import get_reasoning_router, RoutingRequest
            user_msg = next((m.get("content") for m in reversed(convo)
                             if m.get("role") == "user" and m.get("content")), "")
            decision = get_reasoning_router().route(RoutingRequest(
                message=user_msg or "", role=role or "junior",
                tools_used=[name for name, _a, _r in tool_log], rounds=len(tool_log)))
            yield {"type": "routing", "think": decision.think,
                   "reason": decision.reason, "confidence": round(decision.confidence, 2),
                   "mode": "reasoning" if decision.think else "fast"}
            no_think = not decision.think
        except Exception:  # noqa: BLE001 — a router fault must never break the turn
            pass  # fall back to the static TOOLLOOP_NO_THINK default
    # Observability: surface which model writes this (already-decided) synthesis,
    # so the hybrid eval can record FAST→8B / THINK→27B ground truth.
    _sc, _sm, _, _ = _synth_route(no_think)
    yield {"type": "synth", "model_id": _sm,
           "tier": "atlas", "no_think": no_think}
    yield from _stream_final_answer(convo, tools, no_think=no_think)


# Sentinel tool for the "finish-tool" loop. With tool_choice="required" the model
# must emit a tool call every round, so it can never burn time generating a
# throwaway answer just to signal "no more tools" (the old double-generation). When
# it has enough — or the question needs no internal tool — it calls `finish`, which
# we intercept (never dispatched) and hand to the single routed synthesis round.
_FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "回答に必要な情報が揃ったら、または社内ツールが不要な質問なら、これを呼ぶこと。"
            "回答文は自分で書かず finish を呼ぶ。finish を呼ぶと最終回答の生成に進む。 "
            "Call this as soon as you have enough to answer, or when no internal tool "
            "is needed. Do NOT write the answer yourself — calling finish triggers the "
            "final answer."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

# Action tools that commit a side effect or produce a deliverable (a file, a booked
# meeting, a quote/email draft) rather than retrieve facts.
_ACTION_TOOLS = {"schedule_meeting", "create_quote", "send_email"}


def _is_terminal_action(name: str, result: str) -> bool:
    """True when an action tool actually COMMITTED (file generated, meeting booked,
    draft produced) — meaning the turn is done and the model must not be allowed to
    re-invoke it. A confirm=false PREVIEW (which asks the rep to confirm first) and a
    failed call are NOT terminal, so the loop keeps going in those cases.

    This is what stops the model from re-calling generate_pptx every round and
    emitting duplicate files: once the deck is built, the turn ends on that result."""
    if not (name in _ACTION_TOOLS or name.startswith("generate_")):
        return False
    if "confirm=true" in result or "【プレビュー】" in result:
        return False  # a preview/draft awaiting the rep's confirmation
    if result.startswith("[error]") or "見つかりません" in result:
        return False  # a failed call — let the model recover
    return True


def stream_chat_turn(convo: list[dict], tools: list[dict] | None = None,
                     role: str | None = None):
    """Web-facing tool loop that *streams the final answer* token-by-token.

    Same loop as `stream_turn` (kept intact for the Gradio apps), but instead of
    a single blocking final completion it streams the answering round so the web
    Assistant feels as live as Review Coach. Yields typed event dicts:
      {"type": "tool", "name", "args", "result"}   — one per executed tool
      {"type": "routing", "think", "reason", "confidence", "mode"}  — synthesis mode
      {"type": "delta", "text"}                     — answer tokens as they arrive
      {"type": "answer", "text"}                    — the full answer (terminal)
    `convo` is mutated in place (demo semantics). Reasoning (`<think>…</think>`)
    is stripped so only the user-facing answer streams. `role` feeds the router."""
    tools = tools if tools is not None else TOOLS
    tool_log: list[tuple[str, str, str]] = []
    from senpai.documents import registry as _docs
    from senpai.retrieval import trace as _trace
    _trace.start()  # begin a retrieval trace for this turn (Retrieval Explorer)
    _docs.start()   # begin the per-turn generated-document buffer (download chips)

    # Tool-selection rounds must KEEP the <think> phase: this reasoning-distill
    # needs to reason before it will emit a tool call. Prefilling an empty
    # <think></think> here makes it skip deliberation and *narrate* the call as
    # prose ("Action: scheduling meeting…") instead of emitting a real tool_call —
    # so nothing runs and the UI shows no tool. (Verified A/B: empty-think → 0 tool
    # calls; think-on → schedule_meeting fires.) The latency knob only applies to
    # the FINAL answer round, which has its own fast/think routing below.
    # finish-tool loop: force a tool call every round (tool_choice="required") so the
    # model never generates a throwaway answer. `finish` is offered alongside the
    # real tools; calling it (or emitting no real tool) ends the loop → synthesis.
    sel_tools = [*tools, _FINISH_TOOL]
    sel_msgs = lambda: _prep(convo, False)
    for round_i in range(config.MAX_TOOL_ROUNDS):
        last_round = round_i == config.MAX_TOOL_ROUNDS - 1
        try:
            resp = client.chat.completions.create(
                model=config.MODEL, messages=sel_msgs(), tools=sel_tools,
                tool_choice="required", temperature=0.0, **_gen_kwargs(True),
            )
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
            try:
                resp = fallback_client.chat.completions.create(
                    model=config.FALLBACK_MODEL, messages=sel_msgs(), tools=sel_tools,
                    tool_choice="required", temperature=0.0, **_gen_kwargs(True),
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

        # Drop the `finish` sentinel — it is never dispatched. The model is done when
        # it calls finish (or emits no real tool) → hand to the routed synthesis round
        # (FAST→8B / THINK→27B), which generates the answer ONCE, streamed.
        real_calls = [(cid, name, args) for cid, name, args in calls if name != "finish"]
        if not real_calls:
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in {"schedule_meeting", "create_quote", "send_email"} or last_name.startswith("generate_"):
                    yield {"type": "answer", "text": last_result}
                    return
            yield from _route_final_answer(convo, tools, tool_log, role)
            return

        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": args}}
            for cid, name, args in real_calls]})
             
        sched_calls = [SchedToolCall(id=cid, name=name, arguments=args) for cid, name, args in real_calls]
        plan = _SCHEDULER.schedule(sched_calls)
        
        # Drain any residual traces left over in the main thread before threading
        _trace.drain()
        _docs.drain()
        
        # Run the ExecutionPlan in parallel via the Engine
        def _ignore_events(evt: dict) -> None:
            pass
        bundle = _ENGINE.run(plan, _ignore_events)
        
        # Reconstruct the tool_log and yield UI events just like the sequential loop
        # We preserve the order of `real_calls`
        batch_id = f"batch_{id(plan)}" if len(real_calls) > 1 else None
        
        for cid, name, args in real_calls:
            # Re-fetch the evidence from the bundle
            ev_frag = bundle.get(cid)
            result = ev_frag.data.get("text", "[error] Missing execution result") if ev_frag else "[error] Task skipped"
            
            # TRUNCATE IF MASSIVE (prevents parallel calls from blowing up context window)
            if len(result) > 1500:
                result = result[:1500] + "\n... [truncated for length]"
            
            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})
            
            ev = {"type": "tool", "name": name, "args": _fmt_args(args), "result": result, "batchId": batch_id}
            
            # Since threads might have dumped into the shared contextvar (or their own),
            # this is a known limitation in M1 for tracing parallel tasks. We do a global drain here.
            # In a future phase, ToolCapability will attach traces to Evidence natively.
            retrieval = _trace.drain() 
            if retrieval:
                ev["retrieval"] = retrieval
            generated = _docs.drain()
            if generated:
                doc = generated[-1]
                ev["document"] = {"doc_id": doc["doc_id"], "kind": doc["kind"],
                                  "filename": doc["filename"], "download_url": doc["download_url"]}
            yield ev

            if _is_terminal_action(name, result):
                # The deliverable is done (file built / meeting booked / draft made).
                # End the turn on its result so the model can't re-invoke it and
                # produce duplicates — and skip the redundant synthesis round.
                yield {"type": "answer", "text": result}
                return

        if last_round:
            # Hit the tool budget — force a final answer from what we have.
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in {"schedule_meeting", "create_quote", "send_email"} or last_name.startswith("generate_"):
                    yield {"type": "answer", "text": last_result}
                    return
            yield from _route_final_answer(convo, tools, tool_log, role)
            return


def _stream_final_answer(convo: list[dict], tools: list[dict] | None, *, no_think: bool = False):
    """Stream one tool-free completion as the answer, stripping any reasoning.
    Emits `delta` events live and a terminal `answer` with the full text.
    `no_think` prefills an empty think block so the reasoning distill skips its
    <think> phase and answers immediately (the dominant latency win)."""
    full, emitted = "", 0
    msgs = _prep(convo, no_think)
    synth_c, synth_m, alt_c, alt_m = _synth_route(no_think)
    try:
        stream = synth_c.chat.completions.create(
            model=synth_m, messages=msgs, temperature=config.SYNTH_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS, stream=True, **_gen_kwargs(no_think),
        )
    except Exception:  # noqa: BLE001 — fall back to a single blocking answer
        try:
            resp = alt_c.chat.completions.create(
                model=alt_m, messages=msgs, temperature=config.SYNTH_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
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
