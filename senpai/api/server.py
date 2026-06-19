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
from dataclasses import asdict
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from senpai import config
from senpai.coach.review import format_review, narrate_review, narration_prompt, review_note
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.knowledge import generate as kgen
from senpai.knowledge import review as kreview
from senpai.knowledge import store as kstore

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
    flags = deal_flags(d, acts, res.band, today=today)
    rep = store.rep_name(store.deal_rep_id(d))
    customer = store.customer_name(d["customer_id"])
    last = _last_activity_date(acts)
    stale_days = (today - date.fromisoformat(last)).days if last else None
    regressed = config.rank_num(d.get("order_rank")) > config.rank_num(d.get("initial_order_rank"))
    row = {
        "deal_id": d["deal_id"],
        "customer": customer,
        "rep": rep,
        "stage": d.get("order_rank", ""),
        "amount": d.get("total_order_amount", 0),
        "band": res.band,
        "chip": _CHIP[res.band],
        "score": res.score,
        "days_stale": stale_days,
        "close_date": d.get("expected_order_date"),
        "slips": 1 if regressed else 0,
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
    flags = deal_flags(d, acts, res.band, today=today)
    return {
        "deal": {
            "deal_id": d["deal_id"],
            "customer": store.customer_name(d["customer_id"]),
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
        "report": None,
    }


# ---------------------------------------------------------------------------
# coach
# ---------------------------------------------------------------------------
class CoachRequest(BaseModel):
    note: str
    deal_id: str | None = None
    narrate: bool = False


# Optional LLM narration. Off unless SENPAI_USE_LLM is truthy, so the coach
# stays deterministic by default; when on, the served model only *rephrases*
# the deterministic findings (never adds facts), with fallback baked in.
USE_LLM = os.environ.get("SENPAI_USE_LLM", "0").lower() not in ("0", "false", "", "no")


@app.post("/api/coach/review")
def coach_review(req: CoachRequest):
    deal = store.get_deal(req.deal_id) if req.deal_id else None
    acts = store.activities_for_deal(req.deal_id) if deal else None
    r = review_note(req.note, deal=deal, notes=acts, report=None)

    narration = None
    llm_model = None
    if USE_LLM and req.narrate:
        out = narrate_review(r, use_llm=True)
        # narrate_review falls back to the deterministic render on any model
        # failure; only treat it as live narration when it actually differs.
        if out and out.strip() != format_review(r).strip():
            narration = out
            llm_model = config.MODEL

    return {
        "teach_note": TEACH_NOTE,
        "sections": COACH_SECTIONS,
        "used_deal": r.used_deal,
        "result": {s["key"]: getattr(r, s["key"]) for s in COACH_SECTIONS},
        "narration": narration,
        "llm_model": llm_model,
    }


def _sse(obj: dict) -> str:
    """Encode one Server-Sent Event frame."""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.post("/api/coach/narrate")
def coach_narrate(req: CoachRequest):
    """Stream the senior commentary token-by-token (SSE) straight from the
    vLLM/OpenAI endpoint. The deterministic Review Coach is computed first and is
    unchanged; this only streams the optional rephrasing. Event types:
      start | thinking | delta | done | fallback | unavailable | error
    The frontend renders deltas live and falls back to the deterministic card on
    `fallback`/`unavailable`/`error`."""
    if not USE_LLM:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "llm_disabled"})]),
            media_type="text/event-stream",
        )

    deal = store.get_deal(req.deal_id) if req.deal_id else None
    acts = store.activities_for_deal(req.deal_id) if deal else None
    r = review_note(req.note, deal=deal, notes=acts, report=None)

    def gen():
        from senpai.llm import client
        yield _sse({"type": "start", "model": config.MODEL})
        full, emitted, last_think = "", 0, 0
        try:
            for piece in client.stream_complete([{"role": "user", "content": narration_prompt(r)}]):
                full += piece
                if "</think>" in full:                         # reasoning done → answer region
                    answer = full.split("</think>", 1)[1].lstrip("\n ")
                elif "<think>" in full:                        # still reasoning
                    answer = ""
                else:                                          # model emitted no <think> at all
                    answer = full
                if answer:
                    new = answer[emitted:]
                    if new:
                        emitted += len(new)
                        yield _sse({"type": "delta", "text": new})
                elif len(full) - last_think >= 48:             # throttled progress while thinking
                    last_think = len(full)
                    yield _sse({"type": "thinking", "chars": len(full)})
            yield _sse({"type": "done", "model": config.MODEL} if emitted else {"type": "fallback"})
        except Exception:  # noqa: BLE001 — server down/timeout → client falls back
            yield _sse({"type": "error", "reason": "unreachable"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/coach/examples")
def coach_examples():
    return {
        "examples": [
            {
                "title": "前向きだが先送り",
                "note": "お客様は社内で検討してから連絡するとのこと。前向きな反応だった。",
                "hint": "決裁者・期日・次の一手が抜けやすい典型例",
            },
            {
                "title": "競合比較中",
                "note": "競合製品と比較中とのこと。価格が高いと言われた。次回までに見積を再提出する予定。",
                "hint": "価格勝負に流される前に差別化軸を考える",
            },
            {
                "title": "初回訪問の報告",
                "note": "初回訪問。先方のPC環境とネットワーク構成を一通り確認できた。担当者は忙しそうだった。",
                "hint": "情報収集に走り、関係構築と関心事の把握が後回しに",
            },
            {
                "title": "部長が前向き",
                "note": "部長は前向きで、ほぼ決まりという感触。現場のIT担当には会えていない。",
                "hint": "決裁者の感触だけで成約間近と判断していないか",
            },
        ]
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
