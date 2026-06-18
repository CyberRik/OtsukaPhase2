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

import os
from dataclasses import asdict
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from senpai import config
from senpai.coach.review import review_note
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


def _scored_row(d: dict, today: date) -> tuple[dict, list[dict]]:
    notes = store.notes_for_deal(d["deal_id"])
    res = score_deal(d, notes, today=today)
    report = store.report_for_deal(d["deal_id"])
    flags = deal_flags(d, notes, report, res.band, today=today)
    last = d.get("last_contact_date")
    stale_days = (today - date.fromisoformat(last)).days if last else None
    row = {
        "deal_id": d["deal_id"],
        "customer": store.customer_name(d["customer_id"]),
        "rep": store.rep_name(d["rep_id"]),
        "stage": d["stage"],
        "amount": d["amount"],
        "band": res.band,
        "chip": _CHIP[res.band],
        "score": res.score,
        "days_stale": stale_days,
        "close_date": d["expected_close_date"],
        "slips": max(0, len(d.get("close_date_history", [])) - 1),
        "n_flags": len(flags),
        "decision_maker_identified": d.get("decision_maker_identified", False),
        "rep_close_likelihood": d.get("rep_close_likelihood"),
    }
    flag_rows = [
        {
            "deal_id": d["deal_id"],
            "customer": store.customer_name(d["customer_id"]),
            "rep": store.rep_name(d["rep_id"]),
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
    reps = sorted({r["rep"] for d in store.open_deals()
                   for r in [{"rep": store.rep_name(d["rep_id"])}]})
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
    notes = store.notes_for_deal(deal_id)
    res = score_deal(d, notes, today=today)
    report = store.report_for_deal(deal_id)
    flags = deal_flags(d, notes, report, res.band, today=today)
    return {
        "deal": {
            "deal_id": d["deal_id"],
            "customer": store.customer_name(d["customer_id"]),
            "rep": store.rep_name(d["rep_id"]),
            "stage": d["stage"],
            "amount": d["amount"],
            "expected_close_date": d.get("expected_close_date"),
            "last_contact_date": d.get("last_contact_date"),
            "decision_maker_identified": d.get("decision_maker_identified", False),
            "rep_close_likelihood": d.get("rep_close_likelihood"),
            "close_date_history": d.get("close_date_history", []),
            "stage_history": d.get("stage_history", []),
            "products": d.get("products", []),
        },
        "score": res.score,
        "band": res.band,
        "signals": [asdict(s) for s in sorted(res.signals, key=lambda x: x.points, reverse=True)],
        "flags": [asdict(f) for f in flags],
        "notes": notes,
        "report": report,
    }


# ---------------------------------------------------------------------------
# coach
# ---------------------------------------------------------------------------
class CoachRequest(BaseModel):
    note: str
    deal_id: str | None = None


@app.post("/api/coach/review")
def coach_review(req: CoachRequest):
    deal = store.get_deal(req.deal_id) if req.deal_id else None
    notes = store.notes_for_deal(req.deal_id) if deal else None
    report = store.report_for_deal(req.deal_id) if deal else None
    r = review_note(req.note, deal=deal, notes=notes, report=report)
    return {
        "teach_note": TEACH_NOTE,
        "sections": COACH_SECTIONS,
        "used_deal": r.used_deal,
        "result": {s["key"]: getattr(r, s["key"]) for s in COACH_SECTIONS},
    }


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
