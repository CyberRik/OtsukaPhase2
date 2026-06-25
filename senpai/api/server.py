"""FastAPI bridge — exposes the existing Senpai engines as JSON for the web UI.

Run:
    uvicorn senpai.api.server:app --reload --port 8000

Every handler is a thin serialiser over functions the Streamlit apps already
call. Nothing here changes scoring, coaching, or the knowledge pipeline; it only
reshapes their results into JSON the Next.js frontend consumes.

Design contract (kept stable for the frontend):
    GET  /api/health
    GET  /api/dashboard           team rows + KPIs + reliability flags
    GET  /api/deals/{deal_id}     one deal: signals, flags, notes, report
    POST /api/coach/review        free-text note -> a senior's reasoning scaffold
    GET  /api/coach/examples      seed notes for the demo "try one" state
    GET  /api/knowledge/principles
    GET  /api/knowledge/sources
    GET  /api/knowledge/items
    POST /api/knowledge/generate          {principle_id} -> draft item
    POST /api/knowledge/items/{id}/review {action, reviewer, notes}
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from senpai import config
from senpai.coach.cases import find_similar_cases
from senpai.coach.context import build_commentary_context
from senpai.coaching import coaching_workspace
from senpai.coach.profile import rep_coaching_profile, team_coaching_profiles
from senpai.coach.progress import rep_progress
from senpai.growth import junior_reps, rep_growth
from senpai.coach.review import (
    commentary_prompt,
    format_review,
    narrate_review,
    narration_prompt,
    narration_prompt_en,
    review_note,
)
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.knowledge import generate as kgen
from senpai.knowledge import review as kreview
from senpai.knowledge import store as kstore
from senpai.retrieval.playbook import find_similar_deals
from senpai.tools.web import web_search_typed

app = FastAPI(title="Senpai API", version="1.0", docs_url="/api/docs")

# The Next.js dev server runs on a different origin; allow it (and any, for the
# demo). Tighten ALLOWED_ORIGINS in production via env if needed.
_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_CHIP = {"red": "🔴", "yellow": "🟡", "green": "🟢"}

# The six reasoning lenses of the Coach, with the English chrome the UI labels
# them by. Keys match CoachReview fields; the UI renders these in order.
COACH_SECTIONS = [
    {"key": "observations", "ja": "経験豊富な営業が気づくこと", "en": "What a senior notices", "icon": "eye"},
    {"key": "missing_info", "ja": "確認できていない情報", "en": "Missing information", "icon": "search"},
    {"key": "risks", "ja": "リスクの兆候", "en": "Risk signals", "icon": "alert"},
    {"key": "questions", "ja": "次に聞くとよい質問", "en": "Questions to ask next", "icon": "message"},
    {"key": "next_actions", "ja": "取りうる次の一手", "en": "Possible next moves", "icon": "route"},
    {"key": "decision_factors", "ja": "判断に影響する要因", "en": "What should drive the choice", "icon": "scale"},
]

TEACH_NOTE = ("正解を一つ示すものではありません。先輩なら何に注目するか、"
              "その思考の型を提示します。状況に応じて自分で選んでください。")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _today() -> date:
    return config.today()


def _last_activity_date(acts: list[dict]) -> str | None:
    """Most recent activity_date for a deal (acts are newest-first)."""
    return next((a.get("activity_date") for a in acts if a.get("activity_date")), None)


def _scored_row(d: dict, today: date) -> tuple[dict, list[dict]]:
    acts = store.activities_for_deal(d["deal_id"])
    res = score_deal(d, acts, today=today)
    flags = deal_flags(d, acts, health_band=res.band, today=today)
    rep = store.rep_name(store.deal_rep_id(d))
    customer = store.customer_name(d["customer_id"])
    last = _last_activity_date(acts)
    stale_days = (today - date.fromisoformat(last)).days if last else None
    
    cd_history = d.get("close_date_history", [])
    slips = max(0, len(cd_history) - 1)
    
    row = {
        "deal_id": d["deal_id"],
        "customer": customer,
        "customer_id": d["customer_id"],
        "rep": rep,
        "stage": d.get("order_rank", ""),
        "amount": d.get("total_order_amount", 0),
        "band": res.band,
        "chip": _CHIP[res.band],
        "score": res.score,
        "days_stale": stale_days,
        "close_date": d.get("expected_order_date"),
        "slips": slips,
        "n_flags": len(flags),
        "decision_maker_identified": d.get("decision_maker_identified", False),
        "rep_close_likelihood": d.get("rep_close_likelihood"),
    }
    flag_rows = [
        {
            "deal_id": d["deal_id"],
            "customer": customer,
            "rep": rep,
            "severity": f.severity,
            "flag": f.name,
            "message": f.message,
        }
        for f in flags
    ]
    return row, flag_rows


def _build_timeline(deal_id: str, acts: list[dict]) -> list[dict]:
    """Chronological event log for a deal — Pillar 2, Experience. Folds the deal's
    sales activities, its quote, and any orders into one ascending timeline, and
    marks stretches of silence (>30 days) so juniors and managers can *see* how
    the deal actually moved. Pure read-over of existing records; the frontend
    localizes the type labels."""
    events: list[dict] = []
    for a in acts:
        d = a.get("activity_date")
        if not d:
            continue
        events.append({
            "date": d,
            "kind": "activity",
            "type": a.get("activity_type", ""),
            "title": a.get("business_card_info") or "",
            "detail": a.get("daily_report") or "",
            "amount": None,
        })
    q = store.quote_for_deal(deal_id)
    if q and q.get("quoted_at"):
        events.append({
            "date": q["quoted_at"], "kind": "quote", "type": q.get("quote_type", ""),
            "title": q.get("product_mid_category") or q.get("product_major_category") or "",
            "detail": "", "amount": q.get("quote_amount"),
        })
    for o in store.orders_for_deal(deal_id):
        if o.get("ordered_at"):
            events.append({
                "date": o["ordered_at"], "kind": "order", "type": "",
                "title": o.get("product_name") or "", "detail": o.get("supplier") or "",
                "amount": o.get("total_sales_amount"),
            })

    events.sort(key=lambda e: e["date"])

    # Insert silence markers between consecutive events more than 30 days apart.
    out: list[dict] = []
    prev: date | None = None
    for ev in events:
        try:
            cur = date.fromisoformat(ev["date"])
        except (ValueError, TypeError):
            cur = None
        if prev and cur and (cur - prev).days > 30:
            out.append({"date": prev.isoformat(), "kind": "gap", "type": "",
                        "title": "", "detail": "", "amount": None,
                        "days": (cur - prev).days})
        out.append(ev)
        if cur:
            prev = cur
    return out


def _principle_payload(p) -> dict:
    return {
        "principle_id": p.principle_id,
        "statement": p.statement,
        "tags": p.tags,
        "status": p.status,
        "interview_ids": p.interview_ids,
        "n_interviews": len(p.interview_ids),
        "support": [asdict(c) for c in p.support],
        "corroborating_surveys": [asdict(c) for c in p.corroborating_surveys],
        "added_by": p.added_by,
        "added_at": p.added_at,
    }


def _item_payload(it) -> dict:
    p = kstore.get_principle(it.provenance.principle_id)
    d = it.to_dict()
    d["confidence"] = it.confidence(p)
    d["principle_statement"] = p.statement if p else ""
    d["n_interviews"] = len(p.interview_ids) if p else 0
    return d


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "today": _today().isoformat(),
            "pinned": bool(os.environ.get("SENPAI_TODAY"))}


# ---------------------------------------------------------------------------
# documents — download a file the chatbot generated (PPTX/DOCX)
# ---------------------------------------------------------------------------
_DOC_MEDIA = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@app.get("/api/documents/{doc_id}")
def download_document(doc_id: str):
    """Serve a generated document by id. Only files in the registry are reachable —
    the endpoint never accepts a raw path. The chat tool event carries the doc_id."""
    from senpai.documents import registry
    rec = registry.get(doc_id)
    if rec is None or not os.path.exists(rec["path"]):
        raise HTTPException(404, f"document {doc_id} not found")
    ext = os.path.splitext(rec["filename"])[1].lower()
    return FileResponse(rec["path"], filename=rec["filename"],
                        media_type=_DOC_MEDIA.get(ext, "application/octet-stream"))


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard(rep: str | None = None):
    today = _today()
    rows, flagged = [], []
    for d in store.open_deals():
        row, frows = _scored_row(d, today)
        rows.append(row)
        flagged.extend(frows)
    if rep and rep != "(all)":
        rows = [r for r in rows if r["rep"] == rep]
        flagged = [f for f in flagged if f["rep"] == rep]

    order = {"high": 0, "medium": 1, "low": 2}
    flagged.sort(key=lambda r: order.get(r["severity"], 3))
    reps = sorted({store.rep_name(store.deal_rep_id(d)) for d in store.open_deals()})
    kpis = {
        "open_deals": len(rows),
        "at_risk": sum(1 for r in rows if r["band"] == "red"),
        "watch": sum(1 for r in rows if r["band"] == "yellow"),
        "healthy": sum(1 for r in rows if r["band"] == "green"),
        "flagged_reports": len(flagged),
        "pipeline_total": sum(r["amount"] for r in rows),
    }
    return {"today": today.isoformat(), "kpis": kpis, "deals": rows,
            "flags": flagged, "reps": reps}


@app.get("/api/deals/{deal_id}")
def deal_detail(deal_id: str):
    d = store.get_deal(deal_id)
    if d is None:
        raise HTTPException(404, f"deal {deal_id} not found")
    today = _today()
    acts = store.activities_for_deal(deal_id)
    res = score_deal(d, acts, today=today)
    flags = deal_flags(d, acts, health_band=res.band, today=today)
    return {
        "deal": {
            "deal_id": d["deal_id"],
            "customer": store.customer_name(d["customer_id"]),
            "customer_id": d["customer_id"],
            "rep": store.rep_name(store.deal_rep_id(d)),
            "stage": d.get("order_rank", ""),
            "amount": d.get("total_order_amount", 0),
            "expected_close_date": d.get("expected_order_date"),
            "last_contact_date": _last_activity_date(acts),
            "decision_maker_identified": d.get("decision_maker_identified", False),
            "rep_close_likelihood": d.get("rep_close_likelihood"),
            "close_date_history": d.get("close_date_history", []),
            "stage_history": d.get("stage_history", []),
            "products": [d["product_category"]] if d.get("product_category") else [],
        },
        "score": res.score,
        "band": res.band,
        "signals": [asdict(s) for s in sorted(res.signals, key=lambda x: x.points, reverse=True)],
        "flags": [asdict(f) for f in flags],
        "notes": [
            {
                "note_id": f"{deal_id}-{i}",
                "date": a.get("activity_date"),
                "channel": a.get("activity_type", ""),
                "text": a.get("daily_report", ""),
            }
            for i, a in enumerate(acts)
        ],
        "timeline": _build_timeline(deal_id, acts),
        "report": None,
    }


# ---------------------------------------------------------------------------
# coach
# ---------------------------------------------------------------------------
class CoachRequest(BaseModel):
    note: str
    deal_id: str | None = None
    narrate: bool = False
    lang: str = "ja"  # narration output language ("ja" | "en") — presentation only
    conversation_id: str | None = None  # reuse a built context across re-narrates

class TranslateRequest(BaseModel):
    text: str
    target_lang: str

@app.post("/api/translate")
def translate_text(req: TranslateRequest):
    from senpai.llm.client import simple_complete
    prompt = f"Translate the following text to {req.target_lang}. Return ONLY the translated text. Do not include any other commentary. Original text:\n\n{req.text}"
    translated = simple_complete([{"role": "user", "content": prompt}], temperature=0.0)
    return {"translated_text": translated}


# Optional LLM narration. Off unless SENPAI_USE_LLM is truthy, so the coach
# stays deterministic by default; when on, the served model only *rephrases*
# the deterministic findings (never adds facts), with fallback baked in.
USE_LLM = os.environ.get("SENPAI_USE_LLM", "0").lower() not in ("0", "false", "", "no")


@app.post("/api/coach/review")
@app.post("/api/coach/review")
def coach_review(req: CoachRequest):
    deal = store.get_deal(req.deal_id) if req.deal_id else None
    acts = store.activities_for_deal(req.deal_id) if deal else None
    r = review_note(req.note, deal=deal, notes=acts, report=None)

    # Phase 3: Data vs Reality Check intercept
    reality_check_text = None
    if deal and acts is not None:
        today = _today()
        res = score_deal(deal, acts, today=today)
        flags = deal_flags(deal, acts, health_band=res.band, today=today)
        
        has_optimism_mismatch = any(f.name == "optimism_mismatch" for f in flags)
        rep_likelihood = deal.get("rep_close_likelihood")
        
        if has_optimism_mismatch or (rep_likelihood == "high" and res.band == "red"):
            flag_msgs = [f.message for f in flags if f.name == "optimism_mismatch"]
            reason = flag_msgs[0] if flag_msgs else "担当の見込みとデータの健全度が食い違っています。"
            reality_check_text = f"🚨 データと実態のズレを検知: {reason} 抜け漏れがないか再確認してください。"

    # Phase 1 & 2: Account Context Resolution
    from senpai.matsuda import build_account_context
    customer = None
    if deal:
        customer = store.get_customer(deal.get("customer_id"))
    else:
        customer = store.match_customer_in_text(req.note)

    account_context_payload = None
    if customer:
        try:
            ctx = build_account_context(customer["customer_id"])
            account_context_payload = ctx.to_llm_payload()
        except Exception:
            pass

    narration = None
    llm_model = None
    if USE_LLM and req.narrate:
        out = narrate_review(r, use_llm=True)
        if out and out.strip() != format_review(r).strip():
            narration = out
            llm_model = config.MODEL

    sections = list(COACH_SECTIONS)
    result_dict = {s["key"]: getattr(r, s["key"]) for s in COACH_SECTIONS}

    if reality_check_text:
        sections.insert(0, {
            "key": "reality_check",
            "ja": "データと実態のズレ",
            "en": "Data vs Reality Check",
            "icon": "alert"
        })
        result_dict["reality_check"] = [reality_check_text]

    ctx_text, ctx_meta = build_commentary_context(
        req.note, deal_id=req.deal_id, today=_today(), lang=req.lang)

    return {
        "teach_note": TEACH_NOTE,
        "sections": sections,
        "used_deal": r.used_deal,
        "result": result_dict,
        "narration": narration,
        "llm_model": llm_model,
        "account_context": account_context_payload,
        "resolution": {
            "customer": ctx_meta.get("customer"),
            "deal_id": ctx_meta.get("deal_id"),
            "confidence": ctx_meta.get("confidence", "none"),
            "match_method": ctx_meta.get("match_method", "none"),
            "grounded": ctx_meta.get("has_customer_context", False),
        },
        "explanations": [e.to_dict() for e in getattr(r, "explanations", [])],
    }


def _sse(obj: dict) -> str:
    """Encode one Server-Sent Event frame."""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# Reasoning tags vary by sampling: the model emits either <think> or <thinking>
# (and the matching close). Match both spellings so a reasoning block is never
# leaked into the user-facing answer.
_THINK_CLOSE = re.compile(r"</think(?:ing)?>", re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think(?:ing)?>", re.IGNORECASE)


def _strip_reasoning(full: str) -> str | None:
    """The answer portion of a partial stream with any reasoning block removed.

    Returns None while still inside an unclosed <think>/<thinking> block (the
    caller surfaces a 'thinking' indicator); otherwise the visible answer text."""
    m = _THINK_CLOSE.search(full)
    if m:
        return full[m.end():].lstrip("\n -")
    if _THINK_OPEN.search(full):
        return None
    return full


@app.post("/api/coach/narrate")
def coach_narrate(req: CoachRequest):
    """Stream the Senior Commentary token-by-token (SSE).

    This is an experienced rep's *interpretation* layered on the deterministic
    coach — grounded in a retrieved business-context package (customer, deal
    health, activity, history, similar cases), NOT a restatement of the lenses.
    Reasoning is OFF by default (fast live path); set SENPAI_NARRATE_THINK=1 to let
    the model think first (slower, richer) — either way any <think>/<thinking>
    block is stripped before streaming. The request is pinned to the primary GGUF
    endpoint — on any failure we emit an explicit `unavailable`. Event types:
      start | context | thinking | delta | done | unavailable
    The frontend renders deltas live and shows "Senior commentary unavailable" on
    `unavailable`."""
    if not USE_LLM:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "llm_disabled"})]),
            media_type="text/event-stream",
        )

    # Conversation cache: re-narrating the SAME deal+note in a session reuses the
    # already-built deterministic context package (review_note + commentary context)
    # instead of recomputing it. The build is cheap, but caching keeps the grounded
    # context byte-identical across re-narrates and signals provenance to the UI.
    conversation_id = (req.conversation_id or "default").strip() or "default"
    cache = _COACH_CONTEXTS.get(conversation_id)
    cached_flag = bool(cache and cache["deal_id"] == req.deal_id and cache["note"] == req.note
                       and cache["lang"] == req.lang)
    if cached_flag:
        r, context_text, ctx_meta = cache["r"], cache["context_text"], cache["meta"]
    else:
        deal = store.get_deal(req.deal_id) if req.deal_id else None
        acts = store.activities_for_deal(req.deal_id) if deal else None
        r = review_note(req.note, deal=deal, notes=acts, report=None)
        context_text, ctx_meta = build_commentary_context(
            req.note, deal_id=req.deal_id, today=_today(), lang=req.lang)
        _COACH_CONTEXTS[conversation_id] = {
            "deal_id": req.deal_id, "note": req.note, "lang": req.lang,
            "r": r, "context_text": context_text, "meta": ctx_meta}
    prompt = commentary_prompt(req.note, r, context_text,
                               ctx_meta["has_customer_context"], lang=req.lang,
                               customer_name=ctx_meta.get("customer"),
                               deal_id=ctx_meta.get("deal_id"))

    # Workspace continuity: a grounded review puts its deal/customer "in focus" for
    # the shared conversation, so a follow-up chat turn stays scoped to it.
    if ctx_meta.get("has_customer_context"):
        _seed_chat_focus(conversation_id, ctx_meta.get("customer_id"),
                         ctx_meta.get("customer"), ctx_meta.get("deal_id"))

    def gen():
        from senpai.llm import client
        yield _sse({"type": "start", "model": config.MODEL,
                    "endpoint": config.BASE_URL, "conversation_id": conversation_id})
        # Workspace: this stream produces a `review` artifact. Entity is the
        # resolved deal when one was grounded (deterministic; never a name guess).
        _meta = {"type": "artifact_meta", "kind": "review"}
        if ctx_meta.get("deal_id"):
            _meta["entity_ref"] = {"type": "deal", "id": ctx_meta["deal_id"],
                                   "name": ctx_meta.get("customer")}
        yield _sse(_meta)
        # Tell the UI what real records the read is grounded in (or that none matched).
        yield _sse({"type": "context", "grounded": ctx_meta["has_customer_context"],
                    "customer": ctx_meta["customer"], "deal_id": ctx_meta["deal_id"],
                    "confidence": ctx_meta.get("confidence", "none"),
                    "match_method": ctx_meta.get("match_method", "none"),
                    "candidates": ctx_meta.get("ambiguous_candidates", []),
                    "cached": cached_flag})
        # Customer still unresolved (the note named an ambiguous / near-miss
        # company). Don't generate a senior's read yet — the rep must first pick
        # which customer. Generating now would (a) waste a ~15s call on a read the
        # rep discards, and (b) show a read before the choice is even made. Stop
        # after the candidates; the pick re-runs this grounded.
        if not ctx_meta["has_customer_context"] and ctx_meta.get("ambiguous_candidates"):
            yield _sse({"type": "awaiting_choice"})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        full, emitted, last_think = "", 0, 0
        try:
            for piece in client.stream_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                no_think=not config.NARRATE_THINK, allow_fallback=False,
            ):
                full += piece
                answer = _strip_reasoning(full)                 # hide any reasoning block
                if answer:
                    new = answer[emitted:]
                    if new:
                        emitted += len(new)
                        yield _sse({"type": "delta", "text": new})
                elif answer is None and len(full) - last_think >= 48:
                    last_think = len(full)
                    yield _sse({"type": "thinking", "chars": len(full)})
            if emitted:
                yield _sse({"type": "done", "model": config.MODEL})
            else:
                # Reasoning consumed the whole budget before any answer token (a
                # long <think> block on a contended GPU). Retry once with thinking
                # off so the rep always gets a grounded read, never a blank.
                fb, fb_emitted = "", 0
                for piece in client.stream_complete(
                    [{"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                    no_think=True, allow_fallback=False,
                ):
                    fb += piece
                    ans = _strip_reasoning(fb)
                    new = ans[fb_emitted:] if ans else ""
                    if new:
                        fb_emitted += len(new)
                        yield _sse({"type": "delta", "text": new})
                if fb_emitted:
                    yield _sse({"type": "done", "model": config.MODEL})
                else:
                    yield _sse({"type": "unavailable", "reason": "empty"})
        except Exception:  # noqa: BLE001 — primary endpoint down/timeout (no fallback)
            yield _sse({"type": "unavailable", "reason": "unreachable"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# chat — the tool-calling assistant (junior / manager), streamed over SSE
# ---------------------------------------------------------------------------
# This exposes the SAME tool loop the Streamlit/Gradio chats use (stream_turn +
# the role-scoped tool schemas) to the web product. The model autonomously calls
# the deterministic sales tools — and web_search — grounding every answer in
# store data. Tools are imported here; the openai-backed client is imported
# lazily inside the generator so this module stays importable without a server.
from senpai.tools.schemas import JUNIOR_TOOLS, MANAGER_TOOLS, RESEARCH_TOOLS


# Concise system prompts (mirror senpai/apps/*_chat.py; inlined so we don't import
# gradio). today() is read per-request so a pinned SENPAI_TODAY is respected.
def _junior_system() -> str:
    return (
        "あなたは大塚商会の新人営業を支える『先輩(senpai)』アシスタントです。"
        "社内営業の専門アシスタントであると同時に、汎用アシスタントとしても役立ちます。\n"

        "【社内・顧客・案件・製品に関する質問】"
        "必ずツール(query_spr / search_knowledge / search_products / score_deal_health など)で"
        "社内データ(SPR・プレイブック・顧客環境・案件健全度)を確認してから答えてください。"
        "「どう対応すべきか」を問われたら、まず search_knowledge で社内ナレッジ"
        "(先輩の原則・承認済み事例・プレイブック)を引き、指定された構造化出典ID（例: Playbook PB12）を"
        "そのまま添えること。顧客・会社・製品・案件に関する質問は、回答前に必ず query_spr / "
        "search_knowledge / search_products のいずれかを呼び出して確認すること。"
        "ツールを呼ばずに『社内データに無い』と述べてはいけません。"
        "社内の数値は与えられたものだけを使い、人名や提供者名は絶対に推測・生成しないこと。"
        "製品の相談には search_products / create_quote、訪問調整には schedule_meeting、"
        "連絡文の準備には send_email を使えます(いずれも下書きで、送信・確定はしません)。"
        "社内案件で自信が持てない時は route_to_expert で先輩に橋渡ししてください。\n"

        "【文書作成（PPTX / DOCX）】\n"
        "提案書、稟議書、スライド(PPTX)、文書(DOCX)の作成を依頼されたら、"
        "絶対に口頭で「作成してよいですか？」と許可を求めるのではなく、**直ちに該当ツールを `confirm=False` で呼び出してプレビューを出力**してください。\n"
        "プレビューを見たユーザーが「はい」「作成して」と同意したターンでは、**直ちに同じツールを `confirm=True` で呼び出し**、ファイルを生成してください。\n"
        "ツールを使わずにプレビューを自作（ハルシネーション）したり、Pythonコードを出力することは固く禁じます。\n"

        "【一般的な質問（社外の事実・為替・市場価格・一般知識など）】"
        "汎用アシスタントとして、断らずに役立つ回答をしてください。"
        "市場価格・在庫・為替レート・ニュース・最新の製品仕様や型番など、時間とともに変わる"
        "事実や具体的な数値は、記憶から答えてはいけない。必ず web_search を呼び、結果の出典(URL)"
        "を添えて回答すること。web_search を呼べない/結果が得られない場合はその旨を明示し、"
        "不確かな価格・型番・数値を創作しないこと。"
        "用語の定義や一般的な概念など、時間で変わらない安定した知識のみ、あなたの知識で直接答えてよい。"
        "『社内データに無い』という理由だけで一般的な質問を断ってはいけません。\n"

        "【口調】"
        "経験豊富な先輩として、新人に寄り添い『なぜそうするのか』まで噛み砕いて教える、"
        "丁寧で面倒見のよい語り口。一歩先輩の視点で導く。\n"

        "【共通】"
        "質問の言語に合わせて回答する（英語の質問には英語で答える）。"
        "回答は読みやすいMarkdownで整える: 区切りには短い**太字の見出しラベル**"
        "（例: **状況:** …）や見出しを使い、列挙は箇条書きにし、簡潔かつ実務的にまとめる。"
        f"本日は {_today().isoformat()} です。"
    )


def _manager_system() -> str:
    return (
        "あなたは大塚商会の営業マネージャーを支えるアシスタントです。"
        "チーム運営の専門アシスタントであると同時に、汎用アシスタントとしても役立ちます。\n"

        "【チーム・案件・社内データに関する質問】"
        "チーム全体の案件健全度・日報・パイプラインを把握し、リスクの高い案件や"
        "コーチングが必要な担当を、必ずツールで取得した社内データに基づいて示します。"
        "数字は与えられたものだけを使い、創作しないこと。コーチングの根拠は "
        "search_knowledge で社内ナレッジ(先輩の原則・承認済み事例・プレイブック)を引き、"
        "指定された構造化出典ID（例: Playbook PB12）をそのまま添えて示すこと。"
        "絶対に人名や提供者名を推測・生成しないでください。"
        "製品の確認や見積例には search_products / create_quote、"
        "調整や連絡文の準備には schedule_meeting / send_email を使えます"
        "(いずれも下書きで、送信・確定はしません)。\n"

        "【文書作成（PPTX / DOCX）】\n"
        "提案書、稟議書、スライド(PPTX)、文書(DOCX)の作成を依頼されたら、"
        "絶対に口頭で「作成してよいですか？」と許可を求めるのではなく、**直ちに該当ツールを `confirm=False` で呼び出してプレビューを出力**してください。\n"
        "プレビューを見たユーザーが「はい」「作成して」と同意したターンでは、**直ちに同じツールを `confirm=True` で呼び出し**、ファイルを生成してください。\n"
        "ツールを使わずにプレビューを自作（ハルシネーション）したり、Pythonコードを出力することは固く禁じます。\n"

        "【一般的な質問（社外の事実・為替・市場価格・一般知識など）】"
        "汎用アシスタントとして、断らずに役立つ回答をしてください。"
        "市場価格・在庫・為替レート・ニュース・最新の製品仕様など、時間とともに変わる事実や"
        "具体的な数値は記憶から答えず、必ず web_search を呼んで出典(URL)を添えること。"
        "web_search を呼べない/結果が無い場合はその旨を明示し、不確かな数値を創作しないこと。"
        "時間で変わらない安定した一般知識のみ、あなたの知識で直接答えてよい。"
        "『社内データに無い』という理由だけで一般的な質問を断ってはいけません。\n"

        "【口調】"
        "経験豊富なマネージャーを支える有能なスタッフ・アナリストとして、対等で簡潔に、"
        "要点と数字を先に出す。指導や説教はせず、相手の経験を前提に判断材料を提供することに徹する。\n"

        "【共通】"
        "質問の言語に合わせて回答する。"
        "回答は読みやすいMarkdownで整える: 区切りには短い**太字の見出しラベル**"
        "（例: **要点:** …）や見出しを使い、列挙は箇条書きにし、簡潔にまとめる。"
        f"本日は {_today().isoformat()} です。"
    )


def _research_system() -> str:
    # The research assistant answers "tell me about / research this customer"
    # questions. Strict source priority — internal first, web only to fill gaps —
    # so it stays a grounded research tool, NOT a generic chatbot.
    return (
        "あなたは大塚商会の営業担当が顧客訪問前に使う『顧客リサーチ』アシスタントです。"
        "顧客について調べる質問に、必ずツールを使って答えます。\n"
        "厳守する調査手順（この順序を逆にしないこと）:\n"
        "1. まず query_spr で社内の顧客・案件情報を確認する（英語/ローマ字の社名でも"
        "そのまま渡せば内部で名寄せされる。例: 'Aozora Services'）。\n"
        "2. 案件があれば score_deal_health で健全度、find_similar_deals で類似案件、"
        "lookup_customer_environment でIT環境、get_product_info で製品情報を補う。\n"
        "3. 社内情報で答えられない外部情報（事業内容・業界動向・競合・最新ニュース）が"
        "必要なときに限り web_search を使う。\n"
        "回答ルール: 社内データを最優先で示し、その後に外部情報を添える。"
        "社内に記録がない場合はその旨を明記し、事実を創作しない。"
        "web_search の結果は出典（URL）を添えて引用する。"
        "日本語で、要点を構造化して簡潔に答えます。"
        f"本日は {_today().isoformat()} です。"
    )


_CHAT_ROLES = {
    "junior": (JUNIOR_TOOLS, _junior_system),
    "manager": (MANAGER_TOOLS, _manager_system),
    "research": (RESEARCH_TOOLS, _research_system),
}


@dataclass
class ResearchBundle:
    query: str
    target: str
    resolution: dict
    customer: dict | None = None
    active_deal_id: str | None = None
    active_deal: dict | None = None
    deals: list[dict] = field(default_factory=list)
    activities: list[dict] = field(default_factory=list)
    environment: dict | None = None
    products: list[dict] = field(default_factory=list)
    similar_deals: list[dict] = field(default_factory=list)
    web: dict | None = None
    provenance: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_RESEARCH_PREFIXES = [
    r"^\s*tell\s+me\s+about\s+",
    r"^\s*research\s+",
    r"^\s*background\s+on\s+",
    r"^\s*find\s+out\s+about\s+",
    r"^\s*what\s+should\s+i\s+know\s+about\s+",
    r"^\s*use\s+web_search\s+and\s+tell\s+me\s+about\s+",
    r"^\s*switch\s+to\s+",
]

_RESEARCH_CONTEXTS: dict[str, ResearchBundle] = {}
# Conversation caches (mirror _RESEARCH_CONTEXTS) so a multi-turn session keeps its
# context across turns: the Assistant remembers the account in focus; Review Coach
# reuses the built commentary-context package for the same deal instead of rebuilding.
_CHAT_CONTEXTS: dict[str, dict] = {}        # conversation_id -> {customer_id, customer, deal_id}
_COACH_CONTEXTS: dict[str, dict] = {}       # conversation_id -> {deal_id, note, r, context_text, meta}
_DEAL_ID_RE = re.compile(r"\bD\d{3}\b", flags=re.IGNORECASE)


def _seed_chat_focus(conversation_id: str | None, customer_id: str | None,
                     customer: str | None, deal_id: str | None) -> None:
    """Cross-seed the chat 'account in focus' from a skill turn (a /review or
    /account brief) so a later bare chat follow-up — "what should I do about
    this?" — stays scoped to the same customer even though the user never
    re-typed the name. This is what makes the Workspace one continuous
    conversation across skills and chat, rather than a row of isolated requests.

    Deterministic: the focus is the entity the skill already resolved (or the
    deal's own customer), never a name guess."""
    if not conversation_id:
        return
    if not customer_id and deal_id:
        d = store.get_deal(deal_id)
        if d:
            customer_id = d["customer_id"]
            customer = customer or store.customer_name(customer_id)
    if not customer_id:
        return
    _CHAT_CONTEXTS[conversation_id] = {
        "customer_id": customer_id, "customer": customer, "deal_id": deal_id}
_FOLLOWUP_RE = re.compile(
    r"^\s*(what|who|when|why|how|which|are|is|do|does|should)\b|"
    r"\b(risk|risks|decision maker|last meeting|products?|next|happened|activity|activities)\b|"
    # Japanese continuation/question cues (no word boundaries in Japanese): follow-ups
    # about the account already in focus — 次/何をすべき/リスク/直近/決裁 etc.
    r"(次|今後|何を|どう|なぜ|いつ|誰|リスク|決裁|直近|前回|製品|案件|べき|他には|では)",
    flags=re.IGNORECASE,
)


def _research_target(message: str) -> str:
    target = (message or "").strip()
    for pat in _RESEARCH_PREFIXES:
        target = re.sub(pat, "", target, flags=re.IGNORECASE)
    return target.strip(" \t\r\n?？。.")


def _deal_id_in_text(message: str) -> str | None:
    m = _DEAL_ID_RE.search(message or "")
    return m.group(0).upper() if m else None


def _is_followup(message: str, has_context: bool) -> bool:
    if not has_context or _deal_id_in_text(message):
        return False
    text = (message or "").strip()
    if not text or len(text) > 220:
        return False
    if any(re.search(pat, text, flags=re.IGNORECASE) for pat in _RESEARCH_PREFIXES):
        return False
    return bool(_FOLLOWUP_RE.search(text))


# Japanese research cues. Kept narrow on purpose: paired with a customer-resolution
# check below so coaching questions ("値引きについて教えて") never get hijacked.
_RESEARCH_CUES_JA = ("について教えて", "について調べて", "のことを教えて",
                     "の情報を教えて", "を調べて", "について知りたい",
                     "リサーチ", "背景を教えて")


def _is_research_intent(message: str) -> bool:
    """True when the message is a customer-research request *and* names a customer
    we actually have. Auto-routes those turns to the source-grounded research
    pipeline; everything else stays in the tool-calling loop."""
    msg = (message or "").strip()
    has_cue = (
        any(re.search(p, msg, flags=re.IGNORECASE) for p in _RESEARCH_PREFIXES)
        or any(cue in msg for cue in _RESEARCH_CUES_JA)
    )
    if not has_cue:
        return False
    target = _research_target(msg)
    if not target:
        return False
    return store.resolve_customer_detailed(target).status in ("resolved", "ambiguous")


def _public_customer(c: dict | None) -> dict | None:
    if not c:
        return None
    return {"customer_id": c.get("customer_id"), "name": c.get("name"),
            "industry": c.get("industry"), "size": c.get("size"),
            "profile_tags": c.get("profile_tags", [])}


def _deal_summary(d: dict) -> dict:
    acts = store.activities_for_deal(d["deal_id"])
    res = score_deal(d, acts, today=_today())
    return {
        "deal_id": d["deal_id"],
        "customer": store.customer_name(d["customer_id"]),
        "rep": store.rep_name(store.deal_rep_id(d)),
        "stage": d.get("order_rank"),
        "amount": d.get("total_order_amount"),
        "expected_close_date": d.get("expected_order_date"),
        "product_category": d.get("product_category"),
        "health": {
            "band": res.band,
            "score": res.score,
            "reasons": res.top_reasons(3),
        },
    }


def _activity_summary(a: dict) -> dict:
    return {
        "deal_id": a.get("deal_id"),
        "date": a.get("activity_date"),
        "type": a.get("activity_type"),
        "contact": a.get("business_card_info"),
        "text": a.get("daily_report"),
    }


def _products_for_deals(deals: list[dict]) -> list[dict]:
    categories = {d.get("product_category") for d in deals if d.get("product_category")}
    products = []
    seen = set()
    for p in store.all_products():
        hay = " ".join(str(p.get(k, "")) for k in ("product_name", "major", "mid", "minor", "product_code"))
        if any(cat and (cat in hay or hay in cat) for cat in categories):
            if p["product_code"] not in seen:
                seen.add(p["product_code"])
                products.append(p)
    return products


def _deal_resolution(deal: dict) -> dict:
    c = store.get_customer(deal["customer_id"])
    return {
        "status": "resolved",
        "query": deal["deal_id"],
        "customer": _public_customer(c),
        "candidates": [],
    }


def _build_deal_context_bundle(message: str, target: str, deal: dict) -> ResearchBundle:
    customer = store.get_customer(deal["customer_id"])
    raw_activities = store.activities_for_deal(deal["deal_id"])
    bundle = ResearchBundle(
        query=message,
        target=target,
        resolution=_deal_resolution(deal),
        customer=_public_customer(customer),
        active_deal_id=deal["deal_id"],
        active_deal=_deal_summary(deal),
        deals=[_deal_summary(deal)],
        activities=[_activity_summary(a) for a in raw_activities[:20]],
        environment=store.get_environment(deal["customer_id"]),
        products=_products_for_deals([deal]),
        similar_deals=[_deal_summary(d) for d in find_similar_deals(
            customer_id=deal["customer_id"],
            industry=(customer or {}).get("industry", ""),
        )[:3]],
    )
    bundle.provenance.extend([
        {"source": "active_deal_context", "priority": 1, "deal_id": deal["deal_id"]},
        {"source": "internal_records", "priority": 1, "status": "found"},
        {"source": "deals", "priority": 2, "count": 1},
        {"source": "activities", "priority": 3, "count": len(bundle.activities),
         "truncated": len(raw_activities) > len(bundle.activities)},
        {"source": "environment", "priority": 4,
         "status": "found" if bundle.environment else "not_found"},
    ])
    return bundle


def _open_deals(deals: list[dict]) -> list[dict]:
    return [d for d in deals if config.is_open_rank(d.get("order_rank"))]


def _deal_choices_answer(deals: list[dict]) -> str:
    lines = ["この顧客にはアクティブな案件が複数あります。どの案件について調べるか、案件IDで指定してください。"]
    for d in sorted(deals, key=lambda x: x.get("total_order_amount", 0), reverse=True):
        s = _deal_summary(d)
        lines.append(
            f"- {s['deal_id']}: {s['customer']} / {s['stage']} / "
            f"¥{s['amount']:,} / {s['product_category']} / health={s['health']['band']}"
        )
    return "\n".join(lines)


def _source_event(key: str, label: str, status: str, count: int | None = None,
                  detail: str = "") -> str:
    obj = {"type": "source", "key": key, "label": label, "status": status}
    if count is not None:
        obj["count"] = count
    if detail:
        obj["detail"] = detail
    return _sse(obj)


def _build_research_bundle(message: str, target: str, resolution) -> ResearchBundle:
    bundle = ResearchBundle(
        query=message,
        target=target,
        resolution=resolution.to_dict(),
        customer=_public_customer(resolution.customer),
    )
    if resolution.status != "resolved" or not resolution.customer:
        return bundle

    cid = resolution.customer["customer_id"]
    raw_deals = store.deals_for_customer(cid)
    raw_activities = store.activities_for_customer(cid)
    bundle.deals = [_deal_summary(d) for d in raw_deals]
    bundle.activities = [_activity_summary(a) for a in raw_activities[:20]]
    bundle.environment = store.get_environment(cid)
    bundle.products = _products_for_deals(raw_deals)
    bundle.similar_deals = [_deal_summary(d) for d in find_similar_deals(
        customer_id=cid, industry=resolution.customer.get("industry", ""))[:3]]
    bundle.provenance.extend([
        {"source": "internal_records", "priority": 1, "status": "found"},
        {"source": "deals", "priority": 2, "count": len(bundle.deals)},
        {"source": "activities", "priority": 3, "count": len(bundle.activities),
         "truncated": len(raw_activities) > len(bundle.activities)},
        {"source": "environment", "priority": 4,
         "status": "found" if bundle.environment else "not_found"},
    ])
    return bundle


def _research_summary_prompt(bundle: ResearchBundle) -> str:
    return (
        "You are Senpai's customer research summarizer for Otsuka salespeople.\n"
        "Use ONLY the JSON evidence bundle below. Do not add facts from memory.\n"
        "Internal records have higher priority than web results. If web results are present, "
        "label them as external. If internal records are missing, say that clearly.\n"
        "Answer in concise Japanese with sections useful before a sales conversation.\n\n"
        f"Evidence bundle:\n{json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2)}"
    )


def _ambiguity_answer(candidates: list[dict]) -> str:
    lines = ["該当する可能性のある顧客が複数あります。誤った顧客情報を使わないため、候補を選んでください。"]
    for c in candidates:
        aliases = "、".join(c.get("matched_aliases") or [])
        suffix = f"（一致: {aliases}）" if aliases else ""
        lines.append(f"- {c.get('customer_id')}: {c.get('name')}{suffix}")
    return "\n".join(lines)


def _legacy_research_stream(req: ChatRequest):
    target = _research_target(req.message)
    yield _sse({"type": "start", "model": config.MODEL,
                "endpoint": config.BASE_URL, "role": "research"})

    resolution = store.resolve_customer_detailed(target)
    res_obj = resolution.to_dict()
    yield _sse({"type": "resolve", **res_obj})

    if resolution.status == "ambiguous":
        yield _source_event("internal_records", "Internal Records", "ambiguous",
                            count=len(res_obj["candidates"]))
        yield _source_event("deals", "Deals", "skipped")
        yield _source_event("activities", "Activities", "skipped")
        yield _source_event("environment", "Environment", "skipped")
        yield _source_event("web_search", "Web Search", "skipped",
                            detail="ambiguous_customer")
        yield _sse({"type": "answer", "text": _ambiguity_answer(res_obj["candidates"])})
        yield _sse({"type": "done", "model": config.MODEL})
        return

    bundle = _build_research_bundle(req.message, target, resolution)

    if resolution.status == "resolved":
        yield _source_event("internal_records", "Internal Records", "found", count=1)
        yield _source_event("deals", "Deals",
                            "found" if bundle.deals else "not_found",
                            count=len(bundle.deals))
        yield _source_event("activities", "Activities",
                            "found" if bundle.activities else "not_found",
                            count=len(bundle.activities))
        yield _source_event("environment", "Environment",
                            "found" if bundle.environment else "not_found")
        yield _source_event("web_search", "Web Search", "skipped",
                            detail="internal_record_found")
    else:
        yield _source_event("internal_records", "Internal Records", "not_found")
        yield _source_event("deals", "Deals", "skipped")
        yield _source_event("activities", "Activities", "skipped")
        yield _source_event("environment", "Environment", "skipped")
        web = web_search_typed(f"{target} company overview latest news")
        bundle.web = web
        bundle.provenance.append({"source": "web_search", "priority": 2,
                                  "status": web.get("status"), "query": web.get("query")})
        yield _sse({"type": "web", **web})
        yield _source_event("web_search", "Web Search",
                            "found" if web.get("status") == "found" else "error",
                            count=len(web.get("results") or []),
                            detail=web.get("reason", ""))
        if web.get("status") != "found":
            yield _sse({"type": "unavailable",
                        "reason": "no_internal_record_and_web_unavailable"})
            yield _sse({"type": "done", "model": config.MODEL})
            return

    try:
        from senpai.llm.client import stream_complete
        text = ""
        for piece in stream_complete(
            [{"role": "user", "content": _research_summary_prompt(bundle)}],
            temperature=0.2,
            max_tokens=config.LLM_MAX_TOKENS,
            no_think=True,
            allow_fallback=False,
        ):
            text += piece
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        yield _sse({"type": "answer", "text": text or "リサーチ結果を生成できませんでした。"})
        yield _sse({"type": "done", "model": config.MODEL})
    except Exception:  # noqa: BLE001 - research must not silently use fallback
        yield _sse({"type": "unavailable", "reason": "llm_unreachable"})
        yield _sse({"type": "done", "model": config.MODEL})


def _emit_bundle_sources(bundle: ResearchBundle, cached: bool = False):
    yield _source_event("internal_records", "Internal Records", "found", count=1,
                        detail="cached" if cached else "")
    yield _source_event("deals", "Deals", "found" if bundle.deals else "not_found",
                        count=len(bundle.deals), detail="cached" if cached else "")
    yield _source_event("activities", "Activities",
                        "found" if bundle.activities else "not_found",
                        count=len(bundle.activities), detail="cached" if cached else "")
    yield _source_event("environment", "Environment",
                        "found" if bundle.environment else "not_found",
                        detail="cached" if cached else "")
    yield _source_event("web_search", "Web Search", "skipped",
                        detail="active_deal_context" if bundle.active_deal_id else "internal_record_found")


def _summarize_research_bundle(bundle: ResearchBundle):
    try:
        from senpai.llm.client import stream_complete
        text = ""
        for piece in stream_complete(
            [{"role": "user", "content": _research_summary_prompt(bundle)}],
            temperature=0.2,
            max_tokens=config.LLM_MAX_TOKENS,
            no_think=True,
            allow_fallback=False,
        ):
            text += piece
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        yield _sse({"type": "answer", "text": text or "リサーチ結果を生成できませんでした。"})
        yield _sse({"type": "done", "model": config.MODEL})
    except Exception:  # noqa: BLE001 - research must not silently use fallback
        yield _sse({"type": "unavailable", "reason": "llm_unreachable"})
        yield _sse({"type": "done", "model": config.MODEL})


def research_stream(req: ChatRequest):
    conversation_id = (getattr(req, "conversation_id", None) or "default").strip() or "default"
    cached_bundle = _RESEARCH_CONTEXTS.get(conversation_id)
    target = _research_target(req.message)
    deal_id = _deal_id_in_text(req.message)
    use_cached = _is_followup(req.message, bool(cached_bundle))

    yield _sse({"type": "start", "model": config.MODEL,
                "endpoint": config.BASE_URL, "role": "research",
                "conversation_id": conversation_id})
    # Workspace: this stream produces a `research` artifact. Entity (if any) is
    # surfaced later via the resolve/context events as the customer is grounded.
    yield _sse({"type": "artifact_meta", "kind": "research"})

    if use_cached and cached_bundle:
        cached_bundle.query = req.message
        yield _sse({"type": "context", "status": "active",
                    "conversation_id": conversation_id,
                    "deal_id": cached_bundle.active_deal_id,
                    "customer": cached_bundle.customer,
                    "cached": True})
        for ev in _emit_bundle_sources(cached_bundle, cached=True):
            yield ev
        yield from _summarize_research_bundle(cached_bundle)
        return

    if deal_id:
        deal = store.get_deal(deal_id)
        if not deal:
            yield _sse({"type": "resolve", "status": "not_found", "query": deal_id,
                        "customer": None, "candidates": []})
            yield _source_event("internal_records", "Internal Records", "not_found")
            yield _sse({"type": "unavailable", "reason": "deal_not_found"})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        bundle = _build_deal_context_bundle(req.message, deal_id, deal)
        _RESEARCH_CONTEXTS[conversation_id] = bundle
        yield _sse({"type": "resolve", **bundle.resolution})
        yield _sse({"type": "context", "status": "active",
                    "conversation_id": conversation_id, "deal_id": deal_id,
                    "customer": bundle.customer, "cached": False})
        for ev in _emit_bundle_sources(bundle):
            yield ev
        yield from _summarize_research_bundle(bundle)
        return

    resolution = store.resolve_customer_detailed(target)
    if resolution.status == "not_found":
        # The target may be an action/verb-wrapped request ("create a quotation
        # for akebono") rather than a bare name. Locate the customer named inside
        # the message so we hit internal records (and surface ambiguity) instead
        # of falling through to a web search.
        in_text = store.resolve_customer_in_text(req.message)
        if in_text.status != "not_found":
            resolution = in_text
    res_obj = resolution.to_dict()
    yield _sse({"type": "resolve", **res_obj})

    if resolution.status == "ambiguous":
        yield _source_event("internal_records", "Internal Records", "ambiguous",
                            count=len(res_obj["candidates"]))
        yield _source_event("deals", "Deals", "skipped")
        yield _source_event("activities", "Activities", "skipped")
        yield _source_event("environment", "Environment", "skipped")
        yield _source_event("web_search", "Web Search", "skipped",
                            detail="ambiguous_customer")
        # No textual "which one?" answer: the `resolve` candidates above drive a
        # deterministic picker in the UI (both the /research card and the chat
        # bubble). Emitting an answer too would duplicate the picker as a redundant
        # markdown table — and would pre-empt the picker before the rep has chosen.
        yield _sse({"type": "done", "model": config.MODEL})
        return

    if resolution.status == "resolved" and resolution.customer:
        raw_deals = store.deals_for_customer(resolution.customer["customer_id"])
        active_deals = _open_deals(raw_deals)
        if len(active_deals) > 1:
            yield _source_event("internal_records", "Internal Records", "found", count=1)
            yield _source_event("deals", "Deals", "ambiguous", count=len(active_deals),
                                detail="multiple_active_deals")
            yield _source_event("activities", "Activities", "skipped")
            yield _source_event("environment", "Environment", "skipped")
            yield _source_event("web_search", "Web Search", "skipped",
                                detail="select_deal_first")
            yield _sse({"type": "deal_choices", "status": "ambiguous",
                        "deals": [_deal_summary(d) for d in active_deals]})
            yield _sse({"type": "answer", "text": _deal_choices_answer(active_deals)})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        if len(active_deals) == 1:
            bundle = _build_deal_context_bundle(req.message, target, active_deals[0])
            _RESEARCH_CONTEXTS[conversation_id] = bundle
            yield _sse({"type": "context", "status": "active",
                        "conversation_id": conversation_id,
                        "deal_id": bundle.active_deal_id,
                        "customer": bundle.customer,
                        "cached": False})
            for ev in _emit_bundle_sources(bundle):
                yield ev
            yield from _summarize_research_bundle(bundle)
            return

    bundle = _build_research_bundle(req.message, target, resolution)

    if resolution.status == "resolved":
        for ev in _emit_bundle_sources(bundle):
            yield ev
    else:
        yield _source_event("internal_records", "Internal Records", "not_found")
        yield _source_event("deals", "Deals", "skipped")
        yield _source_event("activities", "Activities", "skipped")
        yield _source_event("environment", "Environment", "skipped")
        web = web_search_typed(f"{target} company overview latest news")
        bundle.web = web
        bundle.provenance.append({"source": "web_search", "priority": 2,
                                  "status": web.get("status"), "query": web.get("query")})
        yield _sse({"type": "web", **web})
        yield _source_event("web_search", "Web Search",
                            "found" if web.get("status") == "found" else "error",
                            count=len(web.get("results") or []),
                            detail=web.get("reason", ""))
        if web.get("status") != "found":
            yield _sse({"type": "unavailable",
                        "reason": "no_internal_record_and_web_unavailable"})
            yield _sse({"type": "done", "model": config.MODEL})
            return

    yield from _summarize_research_bundle(bundle)


class ChatMessage(BaseModel):
    role: str       # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []          # prior user/assistant turns (no system)
    role: str = "junior"                     # "junior" | "manager"
    conversation_id: str | None = None
    context: str = ""                        # attached-file text (chat-over-attachment)


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Stream one assistant turn through the tool loop (SSE).

    The model decides which tools to call; each executed tool is surfaced to the
    UI (name, args, result) before the final answer is sent. Grounded entirely in
    the deterministic store/scoring engine plus web_search. Event types:
      start | tool | delta | answer | done | error
    The final answer streams token-by-token (`delta` events) so the Assistant
    feels as live as Review Coach. On any model/transport failure the loop emits
    a single `answer` with the error text (never a crash).

    Research intent ("tell me about / research <customer>") is auto-detected and
    routed to the dedicated, source-grounded `research_stream` — one Assistant
    surface, the right pipeline behind it."""
    if req.role == "research" or _is_research_intent(req.message):
        return StreamingResponse(
            research_stream(req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    tools, system_fn = _CHAT_ROLES.get(req.role, _CHAT_ROLES["junior"])

    # Conversation context cache: remember the account in focus so follow-ups that
    # don't re-name the customer ("what should I do next?", "what happened recently
    # with this account?") stay scoped to the same customer. This also drives the
    # Phase-1 account-scoped retrieval: the cached customer is injected into the
    # system prompt so the model passes it to search_notes.
    conversation_id = (req.conversation_id or "default").strip() or "default"
    cached_ctx = _CHAT_CONTEXTS.get(conversation_id)
    cust = store.match_customer_in_text(req.message)
    msg_deal = _deal_id_in_text(req.message)
    active: dict | None = None
    cached_flag = False
    if cust:
        active = {"customer_id": cust["customer_id"], "customer": cust.get("name"),
                  "deal_id": msg_deal or (cached_ctx or {}).get("deal_id")}
    elif msg_deal and (d := store.get_deal(msg_deal)):
        active = {"customer_id": d["customer_id"],
                  "customer": store.customer_name(d["customer_id"]), "deal_id": msg_deal}
    elif cached_ctx and _is_followup(req.message, True):
        active, cached_flag = cached_ctx, True
    if active and active.get("customer_id"):
        _CHAT_CONTEXTS[conversation_id] = active

    # Ambiguous customer stem (e.g. "marusan" → 4 丸三 companies) and nothing else
    # pinned it down → surface the candidates instead of guessing one's facts.
    amb_candidates: list[dict] = []
    if not active:
        for c in store.ambiguous_match_in_text(req.message):
            d = next((x for x in store.deals_for_customer(c["customer_id"])
                      if config.is_open_rank(x.get("order_rank"))), None)
            amb_candidates.append({"customer_id": c["customer_id"],
                                   "name": c.get("name", ""),
                                   "deal_id": d["deal_id"] if d else None})

    system = system_fn()
    if active and active.get("customer"):
        focus = active["customer"] + (f"（案件 {active['deal_id']}）" if active.get("deal_id") else "")
        system += (f"\n\n【現在の対象顧客】{focus}。アカウント固有の質問では、"
                   f"search_notes に customer='{active['customer']}' を渡し、この顧客の"
                   f"記録に限定して回答すること。")
    # An ambiguous customer (amb_candidates) short-circuits to the picker below
    # before the LLM runs, so no ambiguity clause is added to the system prompt.

    convo: list[dict] = [{"role": "system", "content": system}]
    for m in req.history:
        if m.role in ("user", "assistant") and m.content:
            convo.append({"role": m.role, "content": m.content})
    # An attached file's extracted text rides along as context for THIS turn only
    # (not persisted into history). The model answers the question grounded in it.
    user_content = req.message
    if req.context.strip():
        user_content = (
            "【添付ファイルの内容 / Attached file content】\n"
            f"{req.context.strip()}\n\n"
            "【質問 / Question】\n"
            f"{req.message}"
        )
    convo.append({"role": "user", "content": user_content})

    def gen():
        from senpai.llm.client import stream_chat_turn  # lazy: keep import light
        yield _sse({"type": "start", "model": config.MODEL,
                    "endpoint": config.BASE_URL, "role": req.role,
                    "conversation_id": conversation_id})
        if active:
            yield _sse({"type": "context", "status": "active",
                        "conversation_id": conversation_id,
                        "customer": active.get("customer"),
                        "deal_id": active.get("deal_id"), "cached": cached_flag})
        elif amb_candidates:
            # Ambiguous customer and nothing else pinned it down → surface the
            # candidates and STOP. The deterministic picker is the whole response;
            # running the LLM here only produces a redundant "which one?" message
            # that duplicates the picker and pre-empts the rep's choice. The pick
            # re-runs this turn in place, grounded on the chosen customer.
            yield _sse({"type": "resolve", "status": "ambiguous",
                        "query": req.message, "candidates": amb_candidates})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        try:
            for ev in stream_chat_turn(convo, tools=tools, role=req.role):
                yield _sse(ev)
            yield _sse({"type": "done", "model": config.MODEL})
        except Exception as e:  # noqa: BLE001 — never crash the stream
            yield _sse({"type": "error", "reason": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/coach/similar-cases")
def coach_similar_cases(req: CoachRequest):
    """Real past deals that rhyme with the current situation — Pillar 2,
    Experience. Read-only retrieval over closed deals; each case carries its
    outcome and the validated principle it teaches (see senpai.coach.cases)."""
    deal = store.get_deal(req.deal_id) if req.deal_id else None
    cases = find_similar_cases(req.note, deal=deal, max_n=3, today=_today())
    return {"cases": cases}


@app.get("/api/coach/examples")
def coach_examples():
    # Each seed example is anchored to a REAL, stable deal_id, so "try one" always
    # runs the grounded path (build_commentary_context resolves the deal at high
    # confidence) — never the "no matching customer" fallback. The notes are
    # deliberately customer-AGNOSTIC: the seed regenerates (deal_id is stable but
    # its customer/dates are not), so naming a company in the note text would
    # eventually mismatch the deal's actual customer. The deal_id alone grounds it.
    return {
        "examples": [
            {
                "title": "前向きだが決裁者が不明",
                "deal_id": "D001",
                "note": "担当者は前向きで『ほぼ決まり』との感触。受注確度は高いと見ている。"
                        "ただ決裁者にはまだ会えていない。",
                "hint": "高い確度が案件の実態・決裁者の状況と噛み合っているか",
            },
            {
                "title": "競合と比較中",
                "deal_id": "D021",
                "note": "競合製品と比較中。価格が高いと言われ、見積は提示済み。"
                        "次回までに再提案する予定。",
                "hint": "価格勝負に流される前に差別化軸を考える",
            },
            {
                "title": "初回訪問・IT環境を確認",
                "deal_id": "D016",
                "note": "初回訪問。先方のPC環境とネットワーク構成を一通り確認できた。"
                        "担当者は忙しそうだった。",
                "hint": "情報収集に走り、関係構築と決裁者の把握が後回しに",
            },
            {
                "title": "部長は前向き",
                "deal_id": "D008",
                "note": "部長は前向きで好感触。現場のIT担当にはまだ会えていない。",
                "hint": "決裁者の感触だけで成約間近と判断していないか",
            },
        ]
    }


# ---------------------------------------------------------------------------
# account intelligence — account-level (not deal-level) reasoning
# ---------------------------------------------------------------------------
@app.get("/api/customers/resolve")
def resolve_customer(q: str):
    """Deterministic name→customer resolution (alias-aware, never a name guess).
    Used by the Workspace /account skill to turn a typed name into a customer_id.
    Returns {status: resolved|ambiguous|not_found, query, customer, candidates}."""
    return store.resolve_customer_detailed((q or "").strip()).to_dict()


class SmartResolveRequest(BaseModel):
    query: str
    lang: str = "ja"


@app.post("/api/customers/smart-resolve")
def smart_resolve_customer(body: SmartResolveRequest):
    """Intelligent customer resolution: deterministic first, fuzzy near-miss second,
    LLM ranking third.

    Returns:
      { status: "resolved"|"ambiguous"|"not_found",
        query, customer, candidates, suggested_id? }

    - `suggested_id`: the candidate the model considers most likely (may differ from
      candidates[0] after sorting). Only present when the LLM is available.
    - `candidates`: always sorted by LLM confidence when LLM available, else
      deterministic order.
    """
    q = (body.query or "").strip()
    lang = body.lang or "ja"
    if not q:
        return {"status": "not_found", "query": q, "customer": None, "candidates": []}

    # 1. Deterministic resolve — exact / alias
    res = store.resolve_customer_detailed(q)
    if res.status == "resolved":
        return {**res.to_dict(), "suggested_id": res.customer["customer_id"]}

    candidates = []
    if res.status == "ambiguous":
        candidates = res.candidates  # already found via alias index

    # 2. Fuzzy near-miss — enrich "not_found" with difflib candidates
    if not candidates:
        # Build candidates by scoring each alias key the same way fuzzy_match_customer_in_text
        # does: slide a window the length of the key over the query and take the best ratio.
        # Threshold 0.68 and top-5 cap keeps noise out of the LLM prompt.
        import difflib
        FUZZY_THRESHOLD = 0.68
        MAX_CANDIDATES = 5
        scored: list[tuple[float, str]] = []  # (score, customer_id)
        low = q.lower()
        seen_cids: set[str] = set()
        for key, ids in store._alias_index().items():
            if len(key) < 4 or len(ids) != 1:
                continue
            cid = next(iter(ids))
            if cid in seen_cids:
                continue
            klen = len(key)
            best = 0.0
            if klen > len(low):
                best = difflib.SequenceMatcher(None, key, low, autojunk=False).ratio()
            else:
                for start in range(len(low) - klen + 1):
                    r = difflib.SequenceMatcher(None, key, low[start:start + klen], autojunk=False).ratio()
                    if r > best:
                        best = r
            if best >= FUZZY_THRESHOLD:
                seen_cids.add(cid)
                scored.append((best, cid))

        scored.sort(key=lambda x: (-x[0], x[1]))
        from senpai.data.store import CustomerCandidate, get_customer
        candidates = [
            CustomerCandidate(
                customer_id=cid,
                name=(get_customer(cid) or {}).get("name", cid),
                matched_aliases=[],
            )
            for _, cid in scored[:MAX_CANDIDATES]
            if get_customer(cid)
        ]
        if not candidates:
            return {"status": "not_found", "query": q, "customer": None,
                    "candidates": [], "suggested_id": None}


    # 3. LLM ranking — ask the model which candidate best matches the user's query
    suggested_id: str | None = None
    sorted_candidates = candidates  # default: original order

    if USE_LLM and len(candidates) > 1:
        try:
            from senpai.llm import client as llm_client
            names_block = "\n".join(
                f"  {i+1}. {c.customer_id}: {c.name}"
                for i, c in enumerate(candidates)
            )
            if lang == "ja":
                prompt = (
                    f"ユーザーが入力したキーワードは「{q}」です。\n"
                    f"以下の顧客候補の中から、最も可能性が高い顧客を1つ選んでください。\n"
                    f"顧客リスト:\n{names_block}\n\n"
                    "回答形式: 顧客IDのみを返してください（例: C06）。説明不要。"
                )
            else:
                prompt = (
                    f"The user typed: \"{q}\"\n"
                    f"From the following customers, pick the single best match:\n"
                    f"{names_block}\n\n"
                    "Reply with only the customer_id (e.g. C06). No explanation."
                )
            answer = llm_client.simple_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=16, no_think=True,
            ).strip()
            # Extract the first Cxx token from the answer
            import re as _re
            m = _re.search(r"C\d+", answer)
            if m:
                suggested_id = m.group(0)
                # Re-sort: put the suggested candidate first
                sorted_candidates = sorted(
                    candidates,
                    key=lambda c: (0 if c.customer_id == suggested_id else 1, c.customer_id),
                )
        except Exception:  # noqa: BLE001 — LLM failure must never break the picker
            pass

    return {
        "status": "ambiguous" if len(candidates) > 1 else "resolved",
        "query": q,
        "customer": sorted_candidates[0].__dict__ if len(candidates) == 1 else None,
        "candidates": [{"customer_id": c.customer_id, "name": c.name}
                       for c in sorted_candidates],
        "suggested_id": suggested_id or (sorted_candidates[0].customer_id if sorted_candidates else None),
    }



@app.get("/api/account/{customer_id}")
def account(customer_id: str):
    """One grounded roll-up of a whole customer relationship: headline aggregates,
    account health, relationship-trajectory patterns and expansion opportunities.
    Deterministic; see senpai.account."""
    from senpai.account import build_account_summary
    s = build_account_summary(customer_id, today=_today())
    if s is None:
        raise HTTPException(404, f"customer {customer_id} not found")
    return s.to_dict()


@app.post("/api/account/{customer_id}/commentary")
def account_commentary(customer_id: str, lang: str = "ja",
                       conversation_id: str | None = None):
    """Stream a senior account-manager's read of the whole relationship (SSE).
    Grounded in the deterministic account context package; reasoning disabled for
    low latency, pinned to the primary endpoint (no silent fallback). Event types:
      start | context | delta | done | unavailable"""
    from senpai.account import build_account_context, account_commentary_prompt

    if not USE_LLM:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "llm_disabled"})]),
            media_type="text/event-stream",
        )

    context_text, ctx_meta = build_account_context(customer_id, today=_today(), lang=lang)
    if not ctx_meta["has_account"]:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "account_not_found"})]),
            media_type="text/event-stream",
        )
    prompt = account_commentary_prompt(context_text, lang=lang)

    # Workspace continuity: pulling an account brief puts that customer "in focus"
    # for the shared conversation, so a follow-up chat turn stays scoped to it.
    _seed_chat_focus(conversation_id, customer_id, ctx_meta.get("customer"), None)

    def gen():
        from senpai.llm import client
        yield _sse({"type": "start", "model": config.MODEL, "endpoint": config.BASE_URL})
        # Workspace: this stream produces an `account_brief` artifact.
        yield _sse({"type": "artifact_meta", "kind": "account_brief",
                    "entity_ref": {"type": "account", "id": customer_id,
                                   "name": ctx_meta.get("customer")}})
        yield _sse({"type": "context", "customer": ctx_meta["customer"],
                    "customer_id": customer_id, "score": ctx_meta["score"],
                    "band": ctx_meta["band"]})
        full, emitted = "", 0
        try:
            for piece in client.stream_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                no_think=True, allow_fallback=False,
            ):
                full += piece
                if "</think>" in full:
                    answer = full.split("</think>", 1)[1].lstrip("\n ")
                elif "<think>" in full:
                    answer = ""
                else:
                    answer = full
                new = answer[emitted:]
                if new:
                    emitted += len(new)
                    yield _sse({"type": "delta", "text": new})
            if emitted:
                yield _sse({"type": "done", "model": config.MODEL})
            else:
                yield _sse({"type": "unavailable", "reason": "empty"})
        except Exception:  # noqa: BLE001 — primary endpoint down/timeout (no fallback)
            yield _sse({"type": "unavailable", "reason": "unreachable"})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# manager coaching workspace ("where should I coach today?")
# ---------------------------------------------------------------------------
@app.get("/api/coaching")
def coaching():
    """Manager's daily workspace — Needs Coaching queue, team trends, Confidence
    vs Reality, and a weekly digest. Read-only aggregation over the existing
    deal-health + flags engines; see senpai.coaching."""
    return coaching_workspace(today=_today())


@app.get("/api/coach/rep-profile/{employee_id}")
def coach_rep_profile(employee_id: str):
    """Per-rep coaching profile (the 1:1 page): recurring weaknesses grounded in
    real deals + a validated principle + a real case + an action, plus strengths,
    talking points and coaching-thread status. See senpai.coach.profile."""
    return rep_coaching_profile(employee_id, today=_today())


@app.get("/api/coach/rep-profiles")
def coach_rep_profiles():
    """Team rollup: one compact profile per rep, worst-needing-coaching first."""
    return {"reps": team_coaching_profiles(today=_today())}


@app.get("/api/coach/rep-progress/{employee_id}")
def coach_rep_progress(employee_id: str, windows: int = 4):
    """Longitudinal coaching progress for a rep — per-fiscal-year weakness rates,
    per-issue trend, and whether past coaching was acted on. See coach.progress."""
    return rep_progress(employee_id, today=_today(), windows=windows)


@app.get("/api/coach/threads")
def coach_threads(rep_id: str | None = None, deal_id: str | None = None):
    """Manager↔rep coaching threads, filtered by rep or deal (newest first)."""
    if deal_id:
        rows = store.coaching_threads_for_deal(deal_id)
    elif rep_id:
        rows = store.coaching_threads_for_rep(rep_id)
    else:
        rows = store.all_coaching_threads()
    return {"threads": rows}


# ---------------------------------------------------------------------------
# growth (Pillar 3 — Motivation)
# ---------------------------------------------------------------------------
@app.get("/api/growth")
def growth(rep: str | None = None):
    """A junior's 'My Growth' picture — reviews, principles touched, coaching
    streak, monthly activity, and skill progression. Read-only over the store;
    see senpai.growth. `rep` is an employee_id; defaults to the first junior."""
    juniors = junior_reps()
    eid = rep or (juniors[0]["employee_id"] if juniors else "")
    return {
        "growth": rep_growth(eid, today=_today()),
        "juniors": [{"employee_id": r["employee_id"], "name": r["name"]} for r in juniors],
    }


# ---------------------------------------------------------------------------
# knowledge
# ---------------------------------------------------------------------------
@app.get("/api/knowledge/sources")
def knowledge_sources():
    return {"sources": [asdict(s) for s in kstore.all_sources()]}


@app.get("/api/knowledge/principles")
def knowledge_principles():
    ps = [_principle_payload(p) for p in kstore.all_principles()]
    return {
        "principles": ps,
        "counts": {
            "total": len(ps),
            "approved": sum(1 for p in ps if p["status"] == "approved"),
            "pending": sum(1 for p in ps if p["status"] != "approved"),
            "two_source": sum(1 for p in ps if p["n_interviews"] >= 2),
        },
    }


@app.get("/api/knowledge/items")
def knowledge_items():
    items = [_item_payload(it) for it in kstore.all_items()]
    return {
        "items": items,
        "counts": {
            "total": len(items),
            "approved": sum(1 for i in items if i["review"]["status"] == "approved"),
            "pending": sum(1 for i in items if i["review"]["status"] in ("draft", "needs_edit")),
        },
    }


class GenerateRequest(BaseModel):
    principle_id: str
    use_llm: bool = False


@app.post("/api/knowledge/generate")
def knowledge_generate(req: GenerateRequest):
    p = kstore.get_principle(req.principle_id)
    if p is None:
        raise HTTPException(404, f"principle {req.principle_id} not found")
    if p.status != "approved":
        raise HTTPException(400, "only approved principles may seed a draft")
    item = kgen.generate_item(p, use_llm=req.use_llm)
    kstore.save_item(item)
    return {"item": _item_payload(item)}


class AddPrincipleRequest(BaseModel):
    statement: str               # the tacit knowledge / advice (the principle)
    situation: str = ""          # the context the manager is grounding it in
    tags: list[str] = []         # → Coach retrieval
    added_by: str = "manager"


@app.post("/api/knowledge/principles")
def knowledge_add_principle(req: AddPrincipleRequest):
    """Manager-contributed tacit knowledge → a Layer-1 Principle (status
    'candidate'), grounded in a manager-note Source. Written to the ingested
    overlay (committed seed untouched); flows through the existing review queue
    to become an approved principle juniors can see. See senpai.knowledge."""
    from senpai.knowledge.schema import Citation, Principle, Source

    statement = (req.statement or "").strip()
    if not statement:
        raise HTTPException(400, "statement is required")

    sid = kstore.next_source_id()
    kstore.save_source(Source(
        source_id=sid, kind="manager_note", participant_role="manager",
        date=_today().isoformat(), notes=req.situation.strip(),
    ))
    pid = kstore.next_principle_id()
    principle = Principle(
        principle_id=pid, statement=statement,
        support=[Citation(source_id=sid, quote=(req.situation.strip() or statement))],
        tags=[t.strip() for t in req.tags if t.strip()],
        status="candidate", added_by=req.added_by or "manager",
    )
    kstore.save_principle(principle)
    return {"principle": _principle_payload(principle)}


class ReviewRequest(BaseModel):
    action: str          # approve | request_edit | reject
    reviewer: str = "web_reviewer"
    notes: str = ""


@app.post("/api/knowledge/items/{item_id}/review")
def knowledge_item_review(item_id: str, req: ReviewRequest):
    fn = {"approve": kreview.approve, "request_edit": kreview.request_edit,
          "reject": kreview.reject}.get(req.action)
    if fn is None:
        raise HTTPException(400, f"unknown action {req.action}")
    try:
        item = fn(item_id, req.reviewer, req.notes)
    except KeyError:
        raise HTTPException(404, f"item {item_id} not found")
    return {"item": _item_payload(item)}


# --- Multimodal ingestion ---------------------------------------------------
async def _uploads_to_raw_text(
    audio: UploadFile | None, image: UploadFile | None, text: str | None,
) -> str:
    """Transcribe/OCR any uploads and join with raw text. Shared by /api/extract
    (chat-over-attachment) and /api/ingest (structured draft). Raises 400 if empty."""
    import os
    import tempfile

    from senpai.ingestion import multimodal as mm

    parts: list[str] = []
    for upload, extract in ((audio, mm.transcribe_audio), (image, mm.extract_text_from_image)):
        if upload is None:
            continue
        suffix = os.path.splitext(upload.filename or "")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await upload.read())
            tmp_path = tmp.name
        try:
            out = extract(tmp_path)
            if out:
                parts.append(out)
        finally:
            os.unlink(tmp_path)

    if text and text.strip():
        parts.append(text.strip())

    if not parts:
        raise HTTPException(400, "provide at least one of: audio, image, text")
    return "\n\n".join(parts)


@app.post("/api/extract")
async def extract_text(
    audio: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    """Extract plain text from an attachment for chat context.

    Voice note → transcript, image → OCR, or raw text — returns just `raw_text`.
    Unlike /api/ingest this does NOT run structured-activity extraction: the
    workspace chat attaches this text as context and lets the user ask about it.
    Data ingestion is a separate flow (/api/ingest, /api/ingest/save)."""
    raw = await _uploads_to_raw_text(audio, image, text)
    return {"raw_text": raw}


@app.post("/api/ingest")
async def ingest(
    audio: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    """Capture → structured sales-activity draft.

    Accepts a voice note (audio), a business-card/whiteboard photo (image),
    and/or raw text — any combination — and returns an editable draft matching
    the `sales_activities` schema (activity_type, daily_report, business_card_info,
    customer_challenge, product_major_category). Wraps senpai.ingestion.multimodal
    unchanged; falls back to deterministic mock extraction offline (no multimodal
    API key). The draft is NOT persisted — the caller reviews/edits it, then POSTs
    it to /api/ingest/save."""
    from senpai.ingestion import multimodal as mm

    raw = await _uploads_to_raw_text(audio, image, text)
    draft = mm.extract_structured_activity(raw)
    return {"raw_text": raw, "draft": draft, "multimodal": config.have_multimodal()}


class SaveActivityRequest(BaseModel):
    draft: dict                  # edited ActivityDraft (activity_type, daily_report, …)
    customer_id: str
    deal_id: str
    employee_id: str


@app.post("/api/ingest/save")
def ingest_save(req: SaveActivityRequest):
    """Persist a reviewed daily-report draft as a real sales_activities row.

    Builds the record in exact seed shape (correct Japanese fiscal year/quarter,
    rep dept/division, derived order stats) and appends it to the gitignored
    overlay (senpai/data/ingested/) — the committed seed is never mutated. The new
    activity is immediately visible to scoring/timeline for the running process."""
    if not store.get_deal(req.deal_id):
        raise HTTPException(404, f"deal {req.deal_id} not found")
    if not store.get_customer(req.customer_id):
        raise HTTPException(404, f"customer {req.customer_id} not found")
    from senpai.ingestion import persist
    record = persist.save_activity(req.draft, req.customer_id, req.deal_id, req.employee_id)
    return {"saved": True, "activity": record}
