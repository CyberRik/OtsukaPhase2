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
from senpai.llm import usage as _usage
from senpai.tools.impl import dispatch, _truncate_on_boundary
from senpai.tools import conversation as _conversation
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


def _record_stream_usage(usage_obj, msgs: list[dict], output: str, *,
                         model: str, endpoint: str, label: str) -> None:
    """Record token usage for a streamed call: measured from the server's
    usage-only final chunk when present, else a clearly-flagged estimate over the
    prompt + accumulated output."""
    if usage_obj is not None:
        _usage.record(model, endpoint,
                      getattr(usage_obj, "prompt_tokens", 0) or 0,
                      getattr(usage_obj, "completion_tokens", 0) or 0,
                      label=label, streamed=True)
        return
    prompt_text = "\n".join(str(m.get("content", "")) for m in msgs)
    _usage.record(model, endpoint,
                  _usage._estimate_tokens(prompt_text),
                  _usage._estimate_tokens(output),
                  label=label, streamed=True, estimated=True)


def simple_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None, *, no_think: bool = False,
                    allow_fallback: bool = True, fast_decomp: bool = False,
                    label: str = "complete") -> str:
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
        _usage.record_response(resp, model=primary_m, endpoint="primary", label=label)
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Primary server {primary_m} failed ({e}). Trying fallback...")
        resp = alt_c.chat.completions.create(
            model=alt_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
        )
        _usage.record_response(resp, model=alt_m, endpoint="fallback", label=label)
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
                    allow_fallback: bool = True, fast_decomp: bool = False,
                    label: str = "stream") -> Iterator[str]:
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
    # include_usage asks the server for a final usage-only chunk so token
    # accounting on the streaming path is measured, not estimated.
    _opts = {"stream_options": {"include_usage": True}}
    used_model, used_endpoint = primary_m, "primary"
    try:
        stream = primary_c.chat.completions.create(
            model=primary_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
            **_opts, **_gen_kwargs(no_think),
        )
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Synthesis server {primary_m} failed ({e}). Trying {alt_m}...")
        used_model, used_endpoint = alt_m, "fallback"
        stream = alt_c.chat.completions.create(
            model=alt_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
            **_opts, **_gen_kwargs(no_think),
        )
    think_open = think_closed = False
    _usage_obj = None
    _out_chars: list[str] = []
    for chunk in stream:
        if getattr(chunk, "usage", None):
            _usage_obj = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if not delta:
            continue
        reasoning = _delta_reasoning(delta)
        if reasoning:
            _out_chars.append(reasoning)
            if not think_open:
                think_open = True
                yield "<think>"
            yield reasoning
        if delta.content:
            _out_chars.append(delta.content)
            if think_open and not think_closed:
                think_closed = True
                yield "</think>"
            yield delta.content
    _record_stream_usage(_usage_obj, msgs, "".join(_out_chars),
                         model=used_model, endpoint=used_endpoint, label=label)


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
                tool_choice="auto", temperature=0.1, **_gen_kwargs(True),
            )
            _usage.record_response(resp, model=config.MODEL, endpoint="primary", label="tool_loop")
        except Exception as e:
            print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
            try:
                resp = fallback_client.chat.completions.create(
                    model=config.FALLBACK_MODEL, messages=convo, tools=tools,
                    tool_choice="auto", temperature=0.1, **_gen_kwargs(True),
                )
                _usage.record_response(resp, model=config.FALLBACK_MODEL, endpoint="fallback", label="tool_loop")
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
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
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
            if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                answer = last_result
        answer = answer or "⚠️ ツール呼び出しの上限に達しました。"
    yield tool_log, answer


def _fallback_answer(substantive: list[tuple[str, str]]) -> str:
    """A grounded last resort when synthesis yields nothing: the most recent
    substantive tool result, presented plainly. Empty when nothing useful was
    gathered (then the caller keeps the honest '(no response)')."""
    return substantive[-1][1] if substantive else ""


def _downsample_frames(frames: list[dict], cap: int) -> list[dict]:
    """Evenly thin a scroll-frame sequence down to at most `cap` frames so the chat
    browser-replay animates smoothly without bloating the SSE event (and persisted
    history) with every JPEG. Order is preserved."""
    if len(frames) <= cap:
        keep = frames
    else:
        step = len(frames) / cap
        keep = [frames[int(i * step)] for i in range(cap)]
    return [{"url": f.get("url", ""), "index": f.get("index", 0),
             "screenshot_b64": f.get("screenshot_b64", "")} for f in keep]


_ENTITY_DEAL_RE = re.compile(r"\bD\d{3,}\b")
_ENTITY_CUST_RE = re.compile(r"\bC\d{2,}\b")
_AUDIT_RE = re.compile(
    r"\b(?:audit|quarterly|pipeline review|research steps|faceted searches?)\b|"
    r"(?:監査|四半期|パイプライン.*レビュー|調査手順|ファセット検索)",
    re.IGNORECASE,
)
_STEP_RE = re.compile(r"(?:^|\n)\s*(?:\d+[.)]|[-*・])\s+", re.MULTILINE)
_REP_ID_RE = re.compile(r"\bR\d{2,}\b", re.IGNORECASE)
_QUOTE_RE = re.compile(r"['\"]([^'\"]+)['\"]")


def _json_call(prefix: str, idx: int, name: str, args: dict) -> tuple[str, str, str]:
    return (f"{prefix}_{idx}", name, json.dumps(args, ensure_ascii=False))


def _multi_entity_gather_calls(user_msg: str) -> list[tuple[str, str, str]]:
    """Deterministic fan-out for 'compare A, B, C' turns. If the user's message names
    ≥2 DISTINCT, KNOWN entity ids (deals D### / customers C##, validated against the
    store — same id discipline as SessionFocus), return the full gather bundle for all
    of them so the scheduler runs it in a SINGLE parallel round. The served model emits
    only one tool_call per response under the full prompt (verified), so it can't batch
    these itself.

    The bundle is grouped by tool — every deal's `score_deal_health`, then every deal's
    `query_spr`, then each standalone customer's `query_spr` — but since all are
    parallel-safe reads they execute concurrently in one round (no need to phase health
    before records: there is no dependency between them). Customers get records only
    (deal health needs a deal id).

    Returns [] when the pattern doesn't apply → the normal loop runs unchanged. Scoped
    intentionally narrow: explicit ids only, the compare pattern only."""
    if not user_msg:
        return []
    from senpai.data import store  # lazy
    used: set[str] = set()
    deal_ids: list[str] = []
    cust_ids: list[str] = []
    for did in _ENTITY_DEAL_RE.findall(user_msg):
        if did not in used and store.get_deal(did):
            used.add(did)
            deal_ids.append(did)
    for cid in _ENTITY_CUST_RE.findall(user_msg):
        if cid not in used and store.get_customer(cid):
            used.add(cid)
            cust_ids.append(cid)
    if len(used) < 2:   # threshold is DISTINCT entities, not calls
        return []
    gathers: list[tuple[str, dict]] = []
    gathers += [("score_deal_health", {"deal_id": d}) for d in deal_ids]  # all health, grouped
    gathers += [("query_spr", {"deal_id": d}) for d in deal_ids]          # then all deal records
    gathers += [("query_spr", {"customer": c}) for c in cust_ids]         # then customer records
    return [_json_call("exp", i, name, args) for i, (name, args) in enumerate(gathers)]


def _mentioned_customers(user_msg: str) -> list[str]:
    """Known customer display names mentioned in the prompt, in text order."""
    if not user_msg:
        return []
    from senpai.data import store  # lazy
    hits: list[tuple[int, str]] = []
    seen: set[str] = set()
    for c in store.all_customers():
        name = c.get("name", "")
        if not name or name in seen:
            continue
        pos = user_msg.find(name)
        if pos >= 0:
            hits.append((pos, name))
            seen.add(name)
    return [name for _pos, name in sorted(hits)]


def _audit_customers(user_msg: str) -> list[str]:
    customers = _mentioned_customers(user_msg)
    seen = set(customers)
    for line in (user_msg or "").splitlines():
        if not re.search(r"customer|account|顧客|取引先|会社|status|deal status", line, re.IGNORECASE):
            continue
        for quoted in _QUOTE_RE.findall(line):
            if quoted not in seen and not re.fullmatch(r"R\d{2,}|D\d{3,}|C\d{2,}", quoted, re.IGNORECASE):
                seen.add(quoted)
                customers.append(quoted)
    return customers


def _audit_faceted_deal_calls(user_msg: str) -> list[tuple[str, dict]]:
    """Extract simple faceted deal-search bullets from audit prompts."""
    calls: list[tuple[str, dict]] = []
    for raw in (user_msg or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if "status" in low or "current deal" in low:
            continue
        if "similar" in low or "comparable" in low or "類似" in line:
            continue
        if "product code" in low:
            m_code = re.search(r"['\"]?([A-Z]{2,}\d{2,})['\"]?", line)
            if m_code:
                calls.append(("find_deals", {"product_code": m_code.group(1), "limit": 10}))
            continue
        if "deal" not in low and "案件" not in line:
            continue

        quoted = _QUOTE_RE.findall(line)
        args: dict = {"limit": 10}
        if quoted:
            args["product_category"] = quoted[0]
        if len(quoted) >= 2:
            args["industry"] = quoted[1]
        if "won" in low or "受注" in line:
            args["outcome"] = "won"
        elif "lost" in low or "失注" in line:
            args["outcome"] = "lost"
        elif "open" in low or "進行中" in line:
            args["outcome"] = "open"
        amount = re.search(r"(?:over|above|>=|more than)\s*([\d,]+)", low)
        if amount:
            args["min_amount"] = int(amount.group(1).replace(",", ""))
        if any(k in args for k in ("product_category", "industry", "outcome", "min_amount")):
            calls.append(("find_deals", args))
    return calls


def _audit_similar_deal_calls(user_msg: str, customers: list[str]) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for customer in customers:
        # Match: 'Customer' (in the 'Industry' industry)
        pat = re.compile(
            rf"['\"]{re.escape(customer)}['\"]\s*\([^)]*?['\"]([^'\"]+)['\"][^)]*?industry",
            re.IGNORECASE,
        )
        m = pat.search(user_msg or "")
        if m:
            calls.append(("find_similar_deals", {"customer": customer, "industry": m.group(1)}))
    return calls


def _audit_playbook_calls(user_msg: str) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for line in (user_msg or "").splitlines():
        if not re.search(r"scenario|playbook|シナリオ|プレイブック", line, re.IGNORECASE):
            continue
        quoted = _QUOTE_RE.findall(line)
        if quoted:
            query = quoted[0]
            calls.append(("retrieve_playbook", {"query": query, "tags": [query]}))
    return calls


def _audit_gather_calls(user_msg: str) -> list[tuple[str, str, str]]:
    """Deterministic first-round fan-out for large read-only audit prompts.

    The operational system prompt tells the model to call a tool for every numbered
    item. That preserves completeness, but on audit prompts it often becomes one LLM
    round trip per lookup. This narrow expander recognizes the common audit shape and
    issues independent read-only gathers in one scheduler batch; the normal model
    still synthesizes and may ask for any missing follow-up tools afterward.
    """
    if not user_msg or not _AUDIT_RE.search(user_msg):
        return []
    if len(_STEP_RE.findall(user_msg)) < 3:
        return []

    from senpai.data import store  # lazy
    gathers: list[tuple[str, dict]] = []
    seen_reps: set[str] = set()
    for rep_id in _REP_ID_RE.findall(user_msg):
        rep_id = rep_id.upper()
        if rep_id not in seen_reps and store.get_rep(rep_id):
            seen_reps.add(rep_id)
            gathers.append(("query_spr", {"rep_id": rep_id}))

    customers = _audit_customers(user_msg)
    for customer in customers:
        gathers.append(("query_spr", {"customer": customer}))

    if re.search(r"semantic note|search notes?|日報|ノート|notes?", user_msg, re.IGNORECASE):
        note_terms = []
        if re.search(r"budget slashed", user_msg, re.IGNORECASE):
            note_terms.append("budget slashed")
        if "予算削減" in user_msg:
            note_terms.append("予算削減")
        if note_terms:
            query = " OR ".join(note_terms)
            for customer in customers:
                gathers.append(("search_notes", {"customer": customer, "query": query, "limit": 5}))

    gathers.extend(_audit_similar_deal_calls(user_msg, customers))
    gathers.extend(_audit_faceted_deal_calls(user_msg))
    gathers.extend(_audit_playbook_calls(user_msg))

    # Keep the trigger narrow: at least several read-only gathers, otherwise let the
    # model handle the turn normally.
    if len(gathers) < 6:
        return []
    return [_json_call("audit", i, name, args) for i, (name, args) in enumerate(gathers)]


_WS_AFFIRM_RE = None  # lazy-loaded below (avoids import cost when unused)


def _pending_workspace_edit_confirm(convo: list[dict]) -> tuple[str, str] | None:
    """Deterministic confirm-continuation for a pending `edit_workspace_document`
    preview (confirm=False). If the newest user message is a bare affirmation
    ("apply", "保存して", "はい"...) and the most recent assistant tool call was an
    unconfirmed edit_workspace_document, return (path, content) to re-commit with
    confirm=True ourselves — never left to the model to remember or, worse, to
    free-generate a "saved!" answer without ever calling the tool again (the exact
    bug this closes: a write claimed in prose with no tool call behind it)."""
    global _WS_AFFIRM_RE
    if _WS_AFFIRM_RE is None:
        from senpai.planner.selection import _AFFIRM_RE  # lazy: avoid import cycles
        _WS_AFFIRM_RE = _AFFIRM_RE
    user_msg = next((m.get("content") for m in reversed(convo)
                     if m.get("role") == "user" and m.get("content")), "")
    if not user_msg or not _WS_AFFIRM_RE.search(user_msg.strip()):
        return None
    for m in reversed(convo):
        if m.get("role") != "assistant":
            continue
        calls = m.get("tool_calls") or []
        edit_calls = [tc for tc in calls if tc["function"]["name"] == "edit_workspace_document"]
        if not edit_calls:
            continue  # nearest assistant tool turn wasn't an edit — nothing pending
        try:
            args = json.loads(edit_calls[-1]["function"]["arguments"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if args.get("confirm"):
            return None  # already committed — nothing left to confirm
        path, content = args.get("path"), args.get("content")
        return (path, content) if path and content else None
    return None


# Phrasing that signals "mutate a real local file" (apply/add/edit/update/save
# against a file/note/doc) rather than just asking about its contents. Used to
# nudge the model toward actually calling edit_workspace_document instead of
# just describing the merge in prose with no write behind it.
_WORKSPACE_WRITE_INTENT_RE = re.compile(
    r"\b(?:apply|add|append|edit|update|save|write|put)\b.{0,40}\b(?:file|note|notes|doc|document)\b|"
    r"\b(?:file|note|notes|doc|document)\b.{0,20}\b(?:apply|edit|update|add)\b|"
    r"(?:ファイル|メモ|ノート|文書).{0,15}(?:追加|追記|編集|更新|保存|反映|適用)|"
    r"(?:追加|追記|編集|更新|保存|反映|適用).{0,15}(?:ファイル|メモ|ノート|文書)",
    re.IGNORECASE)

_WORKSPACE_WRITE_NUDGE = (
    "（システム注記：ユーザーはローカルファイルへの反映を求めています。まだ "
    "edit_workspace_document が呼ばれていません。他のツールでの説明だけで終わらせず、"
    "変更後の全文を content に入れて edit_workspace_document を confirm=False で呼び出し、"
    "プレビューを提示してください。)"
)


def _wants_workspace_write(user_msg: str) -> bool:
    return bool(user_msg) and bool(_WORKSPACE_WRITE_INTENT_RE.search(user_msg))


def _is_substantive(result: str) -> bool:
    """True when a tool result carries usable info (not an error / not-found). Drives
    both the answer fallback and the unproductive-round spiral guard — so a tool that
    keeps returning real data (multi-entity fan-out) is never mistaken for a spiral."""
    return not (result.startswith("[error]") or "見つかりません" in result
                or "ありません" in result[:20])


def _route_final_answer(convo, tools, tool_log, role, fallback_text: str = ""):
    """Decide FAST vs REASONING for the synthesis round via the ReasoningRouter,
    emit a `routing` event (observability), then stream the answer. Tool-selection
    stays fast regardless; only this round is dynamically routed. When the router
    is "off" we fall back to the static TOOLLOOP_NO_THINK behaviour. `fallback_text`
    is surfaced if synthesis comes back empty, so a turn never shows a blank."""
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
    yield from _stream_final_answer(convo, tools, no_think=no_think,
                                    fallback_text=fallback_text)


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
# meeting, a quote/email draft, a workspace file write/move) rather than retrieve facts.
_ACTION_TOOLS = {"schedule_meeting", "create_quote", "send_email",
                 "edit_workspace_document", "move_workspace_document"}


def _is_terminal_action(name: str, result: str) -> bool:
    """True when an action tool actually COMMITTED (file generated, meeting booked,
    draft produced, workspace file written) — meaning the turn is done and the model
    must not be allowed to re-invoke it. A confirm=false PREVIEW (which asks the rep
    to confirm first) and a failed call are NOT terminal, so the loop keeps going in
    those cases.

    This is what stops the model from re-calling generate_pptx (or re-writing a
    workspace file) every round and emitting duplicates: once the deliverable is
    committed, the turn ends on that result — the tool's own grounded text becomes
    the answer, leaving no room for the model to embellish or fabricate on top of it
    (the earlier bug: claiming a save happened with no commit behind it at all)."""
    if not (name in _ACTION_TOOLS or name.startswith("generate_")):
        return False
    if "プレビュー" in result or "confirm=true" in result.lower():
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
    # Loop-intelligence bookkeeping (per turn): the results already gathered, keyed by
    # (name, canonical-args), plus each tool's count of consecutive UNPRODUCTIVE rounds
    # (ran but returned nothing substantive). Capping unproductive rounds — not total
    # rounds — is deliberate: a tool fetching distinct entities (query_spr for D133,
    # D012, D168) keeps returning real data so it never trips the cap, while a
    # rephrasing spiral (search X→Y→Z, all empty) trips it after two dry rounds.
    # `substantive` keeps the best real tool output so a turn can always answer.
    # `tool_call_count` is a hard absolute cap: once a tool has been dispatched
    # _MAX_CALLS_PER_TOOL times this turn (across all rounds), further calls are
    # short-circuited regardless of how novel each keyword/arg variant is.
    executed: dict[tuple[str, str], str] = {}
    tool_unproductive: dict[str, int] = {}
    tool_total_rounds: dict[str, int] = {}
    tool_call_count: dict[str, int] = {}
    substantive: list[tuple[str, str]] = []   # (tool_name, result) worth answering from
    # Multi-action tracking: committed deliverables (file generated, meeting booked, etc.)
    # so the loop can continue for additional tasks instead of hard-exiting after the first.
    committed_actions: list[tuple[str, str]] = []   # (tool_name, result) of completed actions
    from senpai.documents import registry as _docs
    from senpai.retrieval import trace as _trace
    from senpai.tools import crawl_trace as _crawl
    _trace.start()  # begin a retrieval trace for this turn (Retrieval Explorer)
    _docs.start()   # begin the per-turn generated-document buffer (download chips)
    _crawl.start()  # begin the per-turn web-crawl trace (web_research browse feed)

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
    user_msg = next((m.get("content") for m in reversed(convo)
                     if m.get("role") == "user" and m.get("content")), "")
    # One-shot guard for the write-intent nudge below — fires at most once per
    # turn so a model that still won't call edit_workspace_document can't loop
    # forever; it falls through to a normal (honest, tool-free) answer instead.
    write_nudge_used = False
    for round_i in range(config.MAX_TOOL_ROUNDS):
        last_round = round_i == config.MAX_TOOL_ROUNDS - 1

        # Deterministic confirm-continuation: a bare "apply"/"保存して"/"はい" right
        # after a pending edit_workspace_document preview re-commits that EXACT write
        # ourselves, with confirm=True — the model never gets a chance to skip the
        # call and free-generate a "saved!" answer instead (see _pending_workspace_edit_confirm).
        pending_edit = _pending_workspace_edit_confirm(convo) if round_i == 0 else None
        # Deterministic multi-entity fan-out: on the FIRST round, if the user named ≥2
        # known entities ("compare D133, D012, D168"), issue the gather reads ourselves
        # in ONE parallel round rather than letting the model dribble them out one per
        # round (it emits a single tool_call per response under the full prompt). The
        # scheduler runs them concurrently; the loop then proceeds normally.
        expanded = [] if pending_edit or round_i != 0 else (
            _audit_gather_calls(user_msg) or _multi_entity_gather_calls(user_msg))
        if pending_edit:
            path, content = pending_edit
            calls = [("confirm_edit_0", "edit_workspace_document",
                      json.dumps({"path": path, "content": content, "confirm": True},
                                ensure_ascii=False))]
        elif expanded:
            calls = expanded
        else:
            # tool_choice: FORCE a tool on the first round (the model must gather before
            # it can answer, and must not burn a round writing a throwaway answer). Once
            # we have evidence, relax to "auto" so the model can cleanly STOP — forcing
            # "required" every round is what makes it contort its final answer into a
            # bogus tool argument (the answer-as-arg leak) instead of just finishing.
            #
            # NB: parallel tool calls need "auto"+thinking-off (verified: "required"
            # applies XGrammar structural enforcement that caps output at ONE
            # <tool_call>). But the full operational system prompt suppresses batching
            # regardless (a minimal prompt fans out; this one emits one call even with an
            # explicit batch instruction), so keeping round-0 "required" costs no
            # parallelism we'd otherwise get, and buys the gather guarantee. Deterministic
            # fan-out for the compare pattern is handled by the expander above.
            tool_choice = "required" if not tool_log else "auto"
            try:
                resp = client.chat.completions.create(
                    model=config.MODEL, messages=sel_msgs(), tools=sel_tools,
                    tool_choice=tool_choice, temperature=0.1, **_gen_kwargs(True),
                )
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
                try:
                    resp = fallback_client.chat.completions.create(
                        model=config.FALLBACK_MODEL, messages=sel_msgs(), tools=sel_tools,
                        tool_choice=tool_choice, temperature=0.1, **_gen_kwargs(True),
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
        # Guard the answer-as-arg leak: under forced tool_choice the model sometimes
        # packs its whole final answer (plus a stray <function=finish>/<tool_call> tag)
        # into a tool ARGUMENT instead of finishing. Dispatching that runs a bogus
        # query AND makes the turn generate the answer twice. Drop such calls; if
        # nothing real remains the model is effectively done → clean synthesis below.
        real_calls = [(cid, name, args) for cid, name, args in real_calls
                      if not _is_finish_leak(name, args)]
        if not real_calls:
            if committed_actions:
                # The model is done (called finish) and we have committed deliverables.
                # Route through synthesis so the model writes a coherent summary
                # incorporating all committed results, or fall back to concatenation.
                fallback = "\n\n".join(r for _, r in committed_actions)
                yield from _route_final_answer(convo, tools, tool_log, role, fallback)
                return
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                    yield {"type": "answer", "text": last_result}
                    return
            # The model thinks it's done (finish / no tool), but the user actually
            # asked to mutate a real file and no edit_workspace_document call has
            # happened yet this turn — that combination is exactly the bug where the
            # model free-generates a "saved!" answer with no write behind it. Nudge
            # once instead of letting it finalize.
            if (not write_nudge_used and _wants_workspace_write(user_msg)
                    and not any(name == "edit_workspace_document" for name, _, _ in tool_log)):
                write_nudge_used = True
                # "user", not "system" — this served model's chat template rejects a
                # system message anywhere but index 0 ("System message must be at
                # the beginning"), which broke every turn that reached this nudge
                # mid-conversation. "user" is accepted anywhere and reads the same
                # to the model as an interstitial instruction.
                convo.append({"role": "user", "content": _WORKSPACE_WRITE_NUDGE})
                continue
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return

        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": args}}
            for cid, name, args in real_calls]})

        # Split into FRESH calls (worth running) and the rest (already gathered this
        # turn, or over the per-tool cap). Stale calls are NOT dispatched — they get
        # a terse "already have this" tool response so the model stops re-searching,
        # and they never hit the engine, the timeline, or the synthesis grounding.
        fresh, fresh_ids = [], set()
        seen_keys = set()
        for cid, name, args in real_calls:
            key = (name, _canon_args(args))
            # Freshness: not an exact repeat (dedup) AND this tool hasn't spiraled —
            # i.e. it hasn't run _TOOL_ROUND_CAP consecutive rounds WITHOUT producing
            # anything substantive. Distinct-entity fan-out (query_spr for D133/D012/
            # D168 across rounds) keeps returning real data, so it never trips the cap;
            # a rephrasing spiral (search X→Y→Z, all empty) trips it after two dry rounds.
            # Multiple calls of the same tool WITHIN one round all pass (fan-out intact).
            # _MAX_CALLS_PER_TOOL is a hard absolute cap on total dispatches per tool per
            # turn: prevents keyword-spray spirals where each call is a *fresh* key
            # (different keyword) so the dedup and round-cap never fire.
            max_calls = _MAX_CALLS_BY_TOOL.get(name, _DEFAULT_MAX_CALLS_PER_TOOL)
            if (key not in executed and key not in seen_keys
                    and tool_unproductive.get(name, 0) < _TOOL_ROUND_CAP
                    and tool_total_rounds.get(name, 0) < 10
                    and tool_call_count.get(name, 0) < max_calls):
                fresh.append((cid, name, args))
                fresh_ids.add(cid)
                seen_keys.add(key)

        sched_calls = [SchedToolCall(id=cid, name=name, arguments=args) for cid, name, args in fresh]
        plan = _SCHEDULER.schedule(sched_calls)

        # Drain any residual traces left over in the main thread before threading
        _trace.drain()
        _docs.drain()
        _crawl.drain()

        # Run the ExecutionPlan in parallel via the Engine
        def _ignore_events(evt: dict) -> None:
            pass
        # Snapshot generated-document ids BEFORE the run so a new file can be
        # attributed to its tool call by diffing the process-global registry. This
        # is robust across the threaded SSE path: Starlette resumes this sync
        # generator on different anyio threadpool threads between yields, so the
        # per-turn ContextVar buffer (_docs.start/drain) set on an earlier `next()`
        # is invisible here (different context) and comes back empty. registry._DOCS
        # is a plain module global shared by all threads, so the diff always sees it.
        docs_before = set(_docs._DOCS.keys())
        # Publish the live conversation so grounding-aware tools (generate_pptx/docx)
        # can ground on what's already in focus this session — a company/quote read
        # from a local file, a deal looked up earlier — instead of hallucinating.
        # Set here, in the same synchronous block as the engine run (no yield between),
        # so copy_context() in the engine carries it into the worker threads.
        _conversation.set_conversation(convo)
        bundle = _ENGINE.run(plan, _ignore_events) if fresh else None
        new_doc_ids = [d for d in _docs._DOCS if d not in docs_before]

        # Reconstruct the tool_log and yield UI events just like the sequential loop.
        # We preserve the order of `real_calls`.
        batch_id = f"batch_{id(plan)}" if len(fresh) > 1 else None

        # Per-round productivity, to update the unproductive-round spiral guard below.
        ran_fresh: set[str] = set()
        productive_fresh: set[str] = set()

        for cid, name, args in real_calls:
            key = (name, _canon_args(args))
            if cid not in fresh_ids:
                # Duplicate / over-cap: satisfy the API (every tool_call id needs a
                # response) but don't dispatch, don't surface a card, don't pad the
                # grounding — just nudge the model to answer with what it has.
                cached = executed.get(
                    key, "（取得済み。これ以上検索せず、収集済みの情報で回答してください。）")
                convo.append({"role": "tool", "tool_call_id": cid, "content": cached})
                continue

            ev_frag = bundle.get(cid) if bundle else None
            if not ev_frag:
                result = f"[error] Task skipped (cid={cid} not in bundle fragments. keys: {list(bundle.fragments.keys()) if bundle else 'None'})"
            else:
                result = ev_frag.data.get("text", "[error] Missing execution result")

            # TRUNCATE IF MASSIVE (prevents parallel calls from blowing up context
            # window). Cut on a natural boundary, not mid-string, so a fact — a company
            # name, a quote figure — isn't severed where the model then reads half of it.
            if len(result) > 1500:
                result = _truncate_on_boundary(result, 1500) + "\n... [truncated for length]"
            executed[key] = result
            # Remember genuinely informative results so the turn can always answer,
            # even if the synthesis round comes back empty (see _route_final_answer),
            # and track per-round productivity for the spiral guard.
            ran_fresh.add(name)
            tool_call_count[name] = tool_call_count.get(name, 0) + 1
            if _is_substantive(result):
                productive_fresh.add(name)
                substantive.append((name, result))

            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})

            ev = {"type": "tool", "name": name, "args": _fmt_args(args), "result": result, "batchId": batch_id}

            # Since threads might have dumped into the shared contextvar (or their own),
            # this is a known limitation in M1 for tracing parallel tasks. We do a global drain here.
            # In a future phase, ToolCapability will attach traces to Evidence natively.
            retrieval = _trace.drain()
            if retrieval:
                ev["retrieval"] = retrieval
            # Attach the pages web_research browsed this round (gated on the tool so
            # crawl pages can't misattribute to a different tool in the batch). Powers
            # the browser-sim replay on the tool card.
            if name == "web_research":
                drained = _crawl.drain()
                if drained:
                    pages = [d for d in drained if d.get("type") != "crawl_frame"]
                    frames = [d for d in drained if d.get("type") == "crawl_frame"]
                    if pages:
                        # Metadata only — the scroll frames carry the visuals, so the
                        # per-page screenshot is stripped to keep the event/history light.
                        ev["crawl"] = [{k: v for k, v in p.items() if k != "screenshot_b64"}
                                       for p in pages]
                    if frames:
                        # Thinned scroll sequence → an auto-playing browser replay on
                        # the chat card (the /intel path streams these live instead).
                        ev["crawlFrames"] = _downsample_frames(frames, 16)
            # Attach the file(s) this call produced. Most generate_* tools emit a single
            # deliverable, but generate_pptx now ships a whole export set (editable PPTX +
            # PDF + the source HTML) from one call, so surface them all as download chips.
            # `document` (singular) stays for backward compat = the primary editable office
            # file (pptx/docx), falling back to the newest id.
            if new_doc_ids and (name.startswith("generate_") or name in _ACTION_TOOLS):
                docs = [d for d in (_docs.get(i) for i in new_doc_ids) if d]
                if docs:
                    ev["documents"] = [{"doc_id": d["doc_id"], "kind": d["kind"],
                                        "filename": d["filename"],
                                        "download_url": d["download_url"]} for d in docs]
                    ev["document"] = next(
                        (d for d in ev["documents"]
                         if d["kind"] in ("pptx", "docx", "proposal", "ringisho")),
                        ev["documents"][-1])
            yield ev

            if _is_terminal_action(name, result):
                # The deliverable is done (file built / meeting booked / draft made).
                # Track it so re-invocation of the SAME tool is suppressed (anti-
                # duplicate), but do NOT exit the loop — the user may have asked
                # for multiple deliverables (e.g. proposal + ringisho) in one turn.
                committed_actions.append((name, result))
                if not last_round:
                    # "user", not "system" — see the write-nudge comment above; this
                    # served model's chat template 400s on a non-leading system message.
                    convo.append({"role": "user", "content":
                        f"✅ {name} が正常に完了しました。ユーザーの元のリクエストを確認してください。"
                        f"依頼されたタスクがすべて完了しましたか？ まだ残っている場合は次のツールを"
                        f"呼び出してください。すべて完了した場合は finish を呼んでください。"})

        # Spiral-guard bookkeeping: a tool that produced something substantive this
        # round resets to 0; one that ran but produced nothing counts an unproductive
        # round. The cap then short-circuits only sustained DRY repetition (a rephrasing
        # spiral), never productive multi-entity fan-out.
        for name in set(ran_fresh):
            tool_unproductive[name] = 0 if name in productive_fresh else tool_unproductive.get(name, 0) + 1
            tool_total_rounds[name] = tool_total_rounds.get(name, 0) + 1

        # Every call this round was a repeat → the model is spinning. Stop looping
        # and synthesize from what we already gathered instead of burning rounds.
        if not fresh:
            if (not write_nudge_used and _wants_workspace_write(user_msg)
                    and not any(name == "edit_workspace_document" for name, _, _ in tool_log)):
                write_nudge_used = True
                # "user", not "system" — this served model's chat template rejects a
                # system message anywhere but index 0 ("System message must be at
                # the beginning"), which broke every turn that reached this nudge
                # mid-conversation. "user" is accepted anywhere and reads the same
                # to the model as an interstitial instruction.
                convo.append({"role": "user", "content": _WORKSPACE_WRITE_NUDGE})
                continue
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return

        if last_round:
            # Hit the tool budget — force a final answer from what we have.
            if committed_actions:
                fallback = "\n\n".join(r for _, r in committed_actions)
                yield from _route_final_answer(convo, tools, tool_log, role, fallback)
                return
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                    yield {"type": "answer", "text": last_result}
                    return
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return


def _stream_final_answer(convo: list[dict], tools: list[dict] | None, *,
                         no_think: bool = False, fallback_text: str = "",
                         label: str = "synthesis", _retry: bool = False):
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
            max_tokens=config.LLM_MAX_TOKENS, stream=True,
            stream_options={"include_usage": True}, **_gen_kwargs(no_think),
        )
    except Exception:  # noqa: BLE001 — fall back to a single blocking answer
        try:
            resp = alt_c.chat.completions.create(
                model=alt_m, messages=msgs, temperature=config.SYNTH_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
            )
            _usage.record_response(resp, model=alt_m, endpoint="fallback", label=label)
            text = re.sub(r"<think>.*?</think>", "",
                          resp.choices[0].message.content or "", flags=re.DOTALL).strip()
            yield {"type": "answer", "text": text or "(no response)"}
        except Exception as fe:  # noqa: BLE001
            yield {"type": "answer", "text": f"⚠️ サーバーエラー: {fe}"}
        return

    _usage_obj = None
    for chunk in stream:
        if getattr(chunk, "usage", None):
            _usage_obj = chunk.usage
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

    _record_stream_usage(_usage_obj, msgs, full,
                         model=synth_m, endpoint="primary", label=label)
    final = re.sub(r"<think>.*?</think>", "", full, flags=re.DOTALL).strip()
    if final:
        yield {"type": "answer", "text": final}
        return
    # Empty answer — the reasoning phase ate the whole token budget, OR disabled
    # thinking broke the generation on this specific prompt (Atlas anomaly).
    # Retry ONCE with the INVERTED thinking mode.
    if not _retry:
        yield from _stream_final_answer(convo, tools, no_think=not no_think,
                                        fallback_text=fallback_text, _retry=True)
        return
    # Still empty even without thinking → surface the gathered evidence directly
    # rather than a blank turn. Only fall back to "(no response)" when we truly have
    # nothing.
    yield {"type": "answer", "text": fallback_text or "(no response)"}


def _fmt_args(arguments) -> str:
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return ", ".join(f"{k}={v!r}" for k, v in d.items())
    except Exception:
        return str(arguments)


_FINISH_LEAK_MARKERS = ("function=finish", "<tool_call>", "</think>", "</function>")
# Real tool args are short ({"deal_id":"D016"}, {"customer":"豊田製作所"}). An argument
# blob far larger than that is the model dumping its prose answer into a field.
_LEAK_ARG_LEN = 600


def _is_finish_leak(name: str, arguments) -> bool:
    """True when the model packed its final answer / a finish sentinel into a tool
    ARGUMENT instead of finishing cleanly (a `tool_choice=required` contortion). Such a
    call must not be dispatched — it runs a bogus query and double-generates the answer.
    Detected by a stray finish/think/tool_call marker or an answer-sized arg blob."""
    args = arguments if isinstance(arguments, str) else json.dumps(arguments or {}, ensure_ascii=False)
    low = args.lower()
    if any(mark in low for mark in _FINISH_LEAK_MARKERS):
        return True
    return len(args) > _LEAK_ARG_LEN


def _canon_args(arguments) -> str:
    """Order-independent, whitespace-normalized args form, for deduping tool calls
    within a turn ({"a":1,"b":2} and {"b":2,"a":1} collapse to one key)."""
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return json.dumps(d, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(arguments)


# A tool that reappears in more than this many ROUNDS in one turn is almost always
# the model spiraling (rephrasing the same query across turns). Past the cap, further
# calls are short-circuited to a "you already have this" nudge instead of a real
# dispatch. Counting rounds (not calls) still allows a single round to fan out many
# parallel calls (the "search 4 laptops at once" case).
_TOOL_ROUND_CAP = 2

# Hard absolute cap on total dispatches of a single tool within one turn. This catches
# keyword-spray spirals (search_products with 40+ different keyword variants per turn)
# where every call has a unique (name, args) key so neither the dedup check nor the
# unproductive-round cap fires. Legitimate database query fan-out (like query_spr,
# search_notes, find_deals) can run up to 30 times to handle large pipeline audit requests.
_MAX_CALLS_BY_TOOL = {
    "search_products": 5,
}
_DEFAULT_MAX_CALLS_PER_TOOL = 30
