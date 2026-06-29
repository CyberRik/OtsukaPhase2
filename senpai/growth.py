"""My Growth — Pillar 3: Motivation.

A read-only analytics layer that turns a rep's real activity history into a
picture of *visible progress*: how much coaching they've done, which validated
principles their work has touched, and a deterministic read on five sales
skills. The purpose is encouragement, not grading — so every number is grounded
in the seed data (no random fluff), and the skill stars come from transparent
ratios over the rep's own deals and activities.

Nothing here changes scoring or coaching. It only queries the store. Each daily
report is treated as one completed coaching review (the rep reflecting on a
call) — the closest real proxy we have to "reviews completed" without persisting
app usage.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from datetime import date, timedelta

from senpai import config
from senpai.data import store
from senpai.knowledge import store as kstore

SKILL_KEYS = [
    "relationship_building",
    "decision_maker_discovery",
    "customer_discovery",
    "closing_discipline",
    "proposal_pricing",
]

# Maps each skill to the coaching issue that flags a gap in that skill.
_SKILL_ISSUE = {
    "decision_maker_discovery": "missing_decision_maker",
    "customer_discovery": "weak_customer_discovery",
    "closing_discipline": "premature_discount",
    "proposal_pricing": "premature_discount",
}

# Keywords in daily_report that signal relationship-building behaviour.
_REL_CUES = ["信頼", "関係", "雑談", "距離", "懇親", "お客様", "ご担当", "ヒアリング"]


def junior_reps() -> list[dict]:
    return [r for r in store.all_reps() if r.get("role") == "junior"]


def _rep_activities(employee_id: str) -> list[dict]:
    return [a for a in store.all_activities()
            if (a.get("sales_info") or {}).get("employee_id") == employee_id]


def _stars(ratio: float) -> int:
    return max(1, min(5, round(1 + ratio * 4)))


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _trunc(text: str, n: int = 80) -> str:
    t = (text or "").strip()
    return t[:n] + "…" if len(t) > n else t


# ---------------------------------------------------------------------------
# Per-month skill ratios (simplified, activity-level signals only)
# ---------------------------------------------------------------------------

def _month_customer_discovery(acts: list[dict]) -> float | None:
    if not acts:
        return None
    filled = sum(1 for a in acts if a.get("customer_challenge"))
    return filled / len(acts)


def _month_decision_maker(acts: list[dict]) -> float | None:
    if not acts:
        return None
    dm_acts = sum(1 for a in acts
                  if any(t in (a.get("business_card_info") or "")
                         for t in config.DECISION_MAKER_TITLES))
    return dm_acts / len(acts)


def _month_relationship(acts: list[dict]) -> float | None:
    if not acts:
        return None
    deals = {a.get("deal_id") for a in acts if a.get("deal_id")}
    if not deals:
        return None
    depth = len(acts) / len(deals)
    return min(1.0, depth / 5.0)


def _month_proposal(acts: list[dict]) -> float | None:
    deal_ids = {a.get("deal_id") for a in acts if a.get("deal_id")}
    if not deal_ids:
        return None
    quoted = sum(1 for did in deal_ids if store.quote_for_deal(did))
    return quoted / len(deal_ids)


_MONTH_SKILL_FN = {
    "relationship_building": _month_relationship,
    "decision_maker_discovery": _month_decision_maker,
    "customer_discovery": _month_customer_discovery,
    "proposal_pricing": _month_proposal,
    # closing_discipline needs won/lost deal data; skip per-month
}


def _month_skill_scores(acts_by_month: dict[str, list[dict]]) -> dict[str, dict[str, float | None]]:
    """Returns {month: {skill_key: ratio | None}} for the trailing months."""
    out: dict[str, dict[str, float | None]] = {}
    for ym, acts in acts_by_month.items():
        scores: dict[str, float | None] = {}
        for key, fn in _MONTH_SKILL_FN.items():
            scores[key] = fn(acts)
        out[ym] = scores
    return out


# ---------------------------------------------------------------------------
# Skill trend: compare recent 2 months vs the 2 before
# ---------------------------------------------------------------------------

def _compute_trend(monthly_scores: list[dict[str, float | None]], skill: str) -> str:
    """'improving' | 'flat' | 'needs_work' from recent vs prior 2-month windows."""
    vals = [m.get(skill) for m in monthly_scores if m.get(skill) is not None]
    if len(vals) < 3:
        return "flat"
    recent = sum(vals[-2:]) / 2
    prior = sum(vals[-4:-2]) / len(vals[-4:-2]) if vals[-4:-2] else vals[0]
    diff = recent - prior
    if diff > 0.12:
        return "improving"
    if diff < -0.12:
        return "needs_work"
    return "flat"


# ---------------------------------------------------------------------------
# Per-skill evidence snippets and insight strings
# ---------------------------------------------------------------------------

def _thread_evidence(threads: list[dict], issue_key: str) -> list[dict]:
    """Up to 2 coaching thread snippets (resolved = positive, open = gap)."""
    matching = [t for t in threads if t.get("issue_key") == issue_key]
    out: list[dict] = []
    for t in sorted(matching, key=lambda x: x.get("created_at", ""), reverse=True)[:2]:
        status = t.get("status", "open")
        positive = status == "resolved"
        # For resolved threads, take the rep's last message (shows what they did).
        # For open/acknowledged, take the manager's message (shows the gap).
        msgs = t.get("messages", [])
        if positive:
            msg = next((m for m in reversed(msgs) if m.get("role") == "rep"), None)
        else:
            msg = next((m for m in msgs if m.get("role") == "manager"), None)
        if msg:
            out.append({
                "text": _trunc(msg["text"]),
                "date": msg.get("date") or t.get("created_at", ""),
                "source": "coaching_thread",
                "deal_id": t.get("deal_id"),
                "positive": positive,
            })
    return out


def _decision_maker_evidence(deals: list[dict], acts: list[dict], threads: list[dict]) -> tuple[list[dict], str]:
    """Evidence + insight for decision_maker_discovery."""
    dm_total = sum(1 for d in deals if d.get("order_rank") in config.DECISION_MAKER_RANKS)
    dm_hit = 0
    biz_card_evidence: list[dict] = []
    for d in deals:
        if d.get("order_rank") not in config.DECISION_MAKER_RANKS:
            continue
        dacts = store.activities_for_deal(d["deal_id"])
        for a in sorted(dacts, key=lambda x: x.get("activity_date", ""), reverse=True):
            bc = a.get("business_card_info") or ""
            if any(t in bc for t in config.DECISION_MAKER_TITLES):
                dm_hit += 1
                if len(biz_card_evidence) < 1:
                    biz_card_evidence.append({
                        "text": _trunc(bc),
                        "date": a.get("activity_date", ""),
                        "source": "activity",
                        "deal_id": d["deal_id"],
                        "positive": True,
                    })
                break

    thread_ev = _thread_evidence(threads, "missing_decision_maker")
    evidence = (biz_card_evidence + thread_ev)[:2]

    if dm_total:
        insight = (f"強いランク案件{dm_total}件中{dm_hit}件で決裁者を特定"
                   if dm_hit else f"強いランク案件{dm_total}件で決裁者がまだ未特定")
    else:
        insight = "強いランク案件がまだありません"

    return evidence, insight


def _customer_discovery_evidence(acts: list[dict], threads: list[dict]) -> tuple[list[dict], str]:
    """Evidence + insight for customer_discovery."""
    filled = [a for a in acts if a.get("customer_challenge")]
    rate = len(filled) / len(acts) if acts else 0.0

    activity_ev: list[dict] = []
    for a in sorted(filled, key=lambda x: x.get("activity_date", ""), reverse=True)[:1]:
        activity_ev.append({
            "text": _trunc(a.get("customer_challenge", "")),
            "date": a.get("activity_date", ""),
            "source": "activity",
            "deal_id": a.get("deal_id"),
            "positive": True,
        })

    thread_ev = _thread_evidence(threads, "weak_customer_discovery")
    evidence = (activity_ev + thread_ev)[:2]

    insight = (f"{len(acts)}件の活動中{len(filled)}件で顧客課題を記録 ({round(rate * 100)}%)")
    return evidence, insight


def _relationship_evidence(deals: list[dict], acts: list[dict]) -> tuple[list[dict], str]:
    """Evidence + insight for relationship_building."""
    n_deals = len(deals)
    n_acts = len(acts)

    # Find the deal with the most activity (deepest engagement).
    act_per_deal: Counter = Counter(a.get("deal_id") for a in acts if a.get("deal_id"))
    evidence: list[dict] = []
    if act_per_deal:
        top_deal_id, top_count = act_per_deal.most_common(1)[0]
        # Pick an activity from that deal that mentions relationship cues.
        top_acts = store.activities_for_deal(top_deal_id)
        anchor = next(
            (a for a in top_acts if any(c in (a.get("daily_report") or "") for c in _REL_CUES)),
            top_acts[0] if top_acts else None,
        )
        if anchor:
            evidence.append({
                "text": _trunc(anchor.get("daily_report") or "", 80),
                "date": anchor.get("activity_date", ""),
                "source": "activity",
                "deal_id": top_deal_id,
                "positive": True,
            })

    avg = round(n_acts / n_deals, 1) if n_deals else 0
    insight = f"{n_deals}件の担当案件で平均{avg}回の接触"
    return evidence, insight


def _closing_evidence(deals: list[dict], threads: list[dict]) -> tuple[list[dict], str]:
    """Evidence + insight for closing_discipline."""
    closed = [d for d in deals if d.get("order_rank") in (config.WON_RANKS | config.DEAD_RANKS)]
    won = [d for d in closed if d.get("order_rank") in config.WON_RANKS]

    evidence: list[dict] = []
    for d in won[:1]:
        evidence.append({
            "text": store.customer_name(d.get("customer_id", "")),
            "date": d.get("rank_updated_at") or d.get("expected_order_date") or "",
            "source": "activity",
            "deal_id": d["deal_id"],
            "positive": True,
        })
    evidence += _thread_evidence(threads, "premature_discount")
    evidence = evidence[:2]

    if closed:
        insight = f"クローズ済み{len(closed)}件中{len(won)}件受注"
    else:
        insight = "まだクローズした案件はありません"
    return evidence, insight


def _proposal_evidence(deals: list[dict], acts: list[dict], threads: list[dict]) -> tuple[list[dict], str]:
    """Evidence + insight for proposal_pricing."""
    n_deals = len(deals)
    quoted = [d for d in deals if store.quote_for_deal(d["deal_id"])]

    evidence: list[dict] = []
    for a in sorted(acts, key=lambda x: x.get("activity_date", ""), reverse=True):
        if a.get("quote_id"):
            evidence.append({
                "text": f"見積 {a['quote_id']} — {store.customer_name(a.get('customer_id', ''))}",
                "date": a.get("activity_date", ""),
                "source": "activity",
                "deal_id": a.get("deal_id"),
                "positive": True,
            })
            break
    evidence += _thread_evidence(threads, "premature_discount")
    evidence = evidence[:2]

    insight = (f"{n_deals}件中{len(quoted)}件で見積を発行" if n_deals
               else "担当案件がまだありません")
    return evidence, insight


# ---------------------------------------------------------------------------
# Principles touched
# ---------------------------------------------------------------------------

_TAG_CUES: dict[str, list[str]] = {
    "決裁者未特定": ["決裁", "部長", "社長", "役員", "担当", "キーマン", "意思決定"],
    "決裁者同席": ["同席", "決裁者", "部長", "役員"],
    "決定先延ばし": ["検討", "先送り", "保留", "また連絡", "持ち帰り", "見送り"],
    "クロージング": ["決定", "クロージング", "契約", "受注", "成約", "締め"],
    "差別化": ["競合", "他社", "比較", "差別化", "強み", "優位"],
    "競合": ["競合", "他社", "相見積", "コンペ", "比較"],
    "提案": ["提案", "見積", "デモ", "プレゼン", "ご提案"],
    "予算": ["予算", "費用", "資金", "コスト"],
    "価格": ["価格", "値引き", "高い", "金額", "単価"],
    "初回訪問": ["初回", "訪問", "顔合わせ", "現地調査"],
    "ヒアリング": ["ヒアリング", "課題", "要望", "困り", "ニーズ"],
    "関係構築": ["関係", "信頼", "雑談", "距離", "距離", "懇親"],
    "情報確認": ["環境", "構成", "確認", "現状", "ネットワーク"],
    "移行": ["移行", "乗り換え", "リプレース", "入れ替え"],
    "案件管理": ["案件", "進捗", "フォロー", "次回"],
    "交渉": ["交渉", "条件", "折衝", "調整"],
    "ステークホルダー": ["関係者", "部署", "利害", "現場"],
}


def _principles_touched(rep: dict, acts: list[dict], month: str | None = None) -> list[str]:
    approved = [p for p in kstore.all_principles() if p.status == "approved"]
    text = " ".join(
        f"{a.get('daily_report') or ''} {a.get('customer_challenge') or ''}"
        for a in acts
        if month is None or (a.get("activity_date") or "")[:7] == month
    )
    out = []
    for p in approved:
        cues = [c for tg in p.tags for c in _TAG_CUES.get(tg, [])]
        if any(c in text for c in cues):
            out.append(p.principle_id)
    return out


# ---------------------------------------------------------------------------
# LLM-based skill assessment (optional — falls back to deterministic)
# ---------------------------------------------------------------------------

_SKILL_CACHE: dict[str, tuple[float, dict]] = {}  # employee_id → (ts, result)
_SKILL_PENDING: set[str] = set()                   # ids with in-flight LLM calls
_CACHE_TTL = 10800                                 # re-score after 3 hours


def _bg_llm_assess(employee_id: str, acts: list[dict], threads: list[dict]) -> None:
    """Runs in a daemon thread; populates cache when done."""
    result = _llm_skill_assessment(acts, threads)
    if result:
        _SKILL_CACHE[employee_id] = (time.time(), result)
    _SKILL_PENDING.discard(employee_id)

def _llm_skill_assessment(acts: list[dict], threads: list[dict]) -> dict[str, dict] | None:
    """Ask the LLM to score skills 0-100 from actual activity text.
    Returns {skill_key: {score: float 0-1, insight: str}} or None on any failure."""
    import json as _json
    import re as _re
    try:
        from senpai.llm.client import fallback_client
        from senpai import config
    except Exception:
        return None

    # Feed the 15 most recent activities (most recent first).
    recent = sorted(acts, key=lambda a: a.get("activity_date", ""), reverse=True)[:15]
    act_lines: list[str] = []
    for a in recent:
        parts = []
        if a.get("daily_report"):
            parts.append(f"報告: {a['daily_report'][:120]}")
        if a.get("customer_challenge"):
            parts.append(f"課題: {a['customer_challenge'][:80]}")
        if a.get("business_card_info"):
            parts.append(f"名刺: {a['business_card_info'][:60]}")
        if parts:
            act_lines.append(f"[{a.get('activity_date', '')}] " + " | ".join(parts))

    if not act_lines:
        return None

    thread_lines: list[str] = []
    for t in threads[:5]:
        msgs = t.get("messages", [])
        if msgs:
            thread_lines.append(
                f"Issue={t.get('issue_key','')} ({t.get('status','')}): "
                f"{msgs[0].get('text', '')[:100]}"
            )

    prompt = (
        "あなたはB2B営業コーチです。以下の新人営業担当者の活動記録とコーチングを読み、"
        "5つのスキルを評価してください。\n\n"
        "【活動記録（最新順）】\n"
        + "\n".join(act_lines)
        + "\n\n【コーチングフィードバック】\n"
        + ("\n".join(thread_lines) if thread_lines else "なし")
        + "\n\n以下のJSONのみ返してください（余分なテキスト不要）:\n"
        '{"relationship_building":{"score":0-100,"insight":"1文"},'
        '"decision_maker_discovery":{"score":0-100,"insight":"1文"},'
        '"customer_discovery":{"score":0-100,"insight":"1文"},'
        '"closing_discipline":{"score":0-100,"insight":"1文"},'
        '"proposal_pricing":{"score":0-100,"insight":"1文"}}\n\n'
        "scoreは実際の活動内容の質を反映してください（0=全く実践なし, 100=理想的な実践）。"
        "insightは活動記録の具体的な内容を根拠にした1文にしてください。"
    )

    try:
        import re as _re2
        from senpai.llm.client import _gen_kwargs
        resp = fallback_client.chat.completions.create(
            model=config.FALLBACK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=600,
            **_gen_kwargs(no_think=True),  # atlas: thinking off + sampling
        )
        raw = resp.choices[0].message.content or ""
        raw = _re2.sub(r"<think>.*?</think>", "", raw, flags=_re2.DOTALL).strip()
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not m:
            return None
        data = _json.loads(m.group())
        result: dict[str, dict] = {}
        for k in SKILL_KEYS:
            if k in data and isinstance(data[k], dict):
                raw_score = data[k].get("score", 50)
                result[k] = {
                    "score": max(0.0, min(1.0, float(raw_score) / 100.0)),
                    "insight": str(data[k].get("insight", "")),
                }
        return result or None
    except Exception as exc:
        print(f"⚠️  LLM skill assessment failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def rep_growth(employee_id: str, today: date | None = None) -> dict:
    today = today or config.today()
    rep = store.get_rep(employee_id) or {}
    deals = store.deals_for_rep(employee_id)
    acts = _rep_activities(employee_id)
    threads = store.coaching_threads_for_rep(employee_id)
    reports = [a for a in acts if a.get("activity_type") == "002_Daily Report"]
    this_month = f"{today.year:04d}-{today.month:02d}"

    # Coaching streak: consecutive weeks with activity, ending at the most recent.
    weeks = {_week_start(date.fromisoformat(a["activity_date"]))
             for a in acts if a.get("activity_date")}
    streak = 0
    if weeks:
        w = max(weeks)
        while w in weeks:
            streak += 1
            w = w - timedelta(days=7)

    # Build the trailing 6-month list (oldest → newest) and group acts by month.
    per_month_count = Counter((a.get("activity_date") or "")[:7] for a in acts if a.get("activity_date"))
    monthly_months: list[str] = []
    y, m = today.year, today.month
    for i in range(5, -1, -1):
        yy, mm = y, m - i
        while mm <= 0:
            mm += 12
            yy -= 1
        monthly_months.append(f"{yy:04d}-{mm:02d}")

    acts_by_month: dict[str, list[dict]] = {ym: [] for ym in monthly_months}
    for a in acts:
        ym = (a.get("activity_date") or "")[:7]
        if ym in acts_by_month:
            acts_by_month[ym].append(a)

    # Per-month skill ratios (for the bar chart overlay and trend computation).
    month_scores_raw = _month_skill_scores(acts_by_month)

    # Ordered list of monthly score dicts for trend computation.
    monthly_score_list = [month_scores_raw.get(ym, {}) for ym in monthly_months]

    # Skills: stars + evidence + insight + trend.
    n_deals = len(deals)
    n_acts = len(acts)
    closed = [d for d in deals if d.get("order_rank") in (config.WON_RANKS | config.DEAD_RANKS)]
    won = [d for d in closed if d.get("order_rank") in config.WON_RANKS]

    # decision_maker_discovery raw ratio (for stars)
    dm_deals = 0
    for d in deals:
        dacts = store.activities_for_deal(d["deal_id"])
        if any(any(t in (a.get("business_card_info") or "") for t in config.DECISION_MAKER_TITLES)
               for a in dacts):
            dm_deals += 1
    dm_ratio = dm_deals / n_deals if n_deals else 0.0

    disc_ratio = (sum(1 for a in acts if a.get("customer_challenge")) / n_acts) if n_acts else 0.0
    depth = (n_acts / n_deals) if n_deals else 0.0
    rel_ratio = min(1.0, depth / 5.0)
    win_ratio = (len(won) / len(closed)) if closed else 0.5
    quoted_count = sum(1 for d in deals if store.quote_for_deal(d["deal_id"]))
    quote_ratio = (quoted_count / n_deals) if n_deals else 0.0

    ratios = {
        "relationship_building": rel_ratio,
        "decision_maker_discovery": dm_ratio,
        "customer_discovery": disc_ratio,
        "closing_discipline": win_ratio,
        "proposal_pricing": quote_ratio,
    }

    # Build per-skill evidence and insights.
    ev_dm, ins_dm = _decision_maker_evidence(deals, acts, threads)
    ev_cd, ins_cd = _customer_discovery_evidence(acts, threads)
    ev_rb, ins_rb = _relationship_evidence(deals, acts)
    ev_cl, ins_cl = _closing_evidence(deals, threads)
    ev_pp, ins_pp = _proposal_evidence(deals, acts, threads)

    skill_extra = {
        "relationship_building": (ev_rb, ins_rb),
        "decision_maker_discovery": (ev_dm, ins_dm),
        "customer_discovery": (ev_cd, ins_cd),
        "closing_discipline": (ev_cl, ins_cl),
        "proposal_pricing": (ev_pp, ins_pp),
    }

    # LLM skill assessment — serve from cache when available, else fire a
    # background thread and fall back to deterministic for this load.
    now = time.time()
    cached_ts, cached_val = _SKILL_CACHE.get(employee_id, (0.0, None))
    if cached_val is not None and now - cached_ts < _CACHE_TTL:
        llm = cached_val
    else:
        llm = None  # deterministic this load
        if employee_id not in _SKILL_PENDING:
            _SKILL_PENDING.add(employee_id)
            threading.Thread(
                target=_bg_llm_assess,
                args=(employee_id, list(acts), list(threads)),
                daemon=True,
            ).start()

    skills = []
    for k in SKILL_KEYS:
        ev, det_insight = skill_extra[k]
        trend = _compute_trend(monthly_score_list, k) if k in _MONTH_SKILL_FN else "flat"
        if llm and k in llm:
            stars = _stars(llm[k]["score"])
            insight = llm[k]["insight"] or det_insight
        else:
            stars = _stars(ratios[k])
            insight = det_insight
        skills.append({
            "key": k,
            "stars": stars,
            "trend": trend,
            "evidence": ev,
            "insight": insight,
        })

    # Principles.
    principles_total = _principles_touched(rep, acts)
    principles_month = _principles_touched(rep, acts, month=this_month)
    reviews_month = sum(1 for a in reports if (a.get("activity_date") or "")[:7] == this_month)
    active_days_month = len({a.get("activity_date") for a in acts
                             if (a.get("activity_date") or "")[:7] == this_month
                             and a.get("activity_date")})

    # Monthly array: count + per-skill ratios (0..1 or null).
    monthly = []
    for ym in monthly_months:
        scores = month_scores_raw.get(ym, {})
        monthly.append({
            "month": ym,
            "count": per_month_count.get(ym, 0),
            "skill_scores": {k: scores.get(k) for k in _MONTH_SKILL_FN},
        })

    return {
        "rep": {
            "employee_id": rep.get("employee_id", employee_id),
            "name": rep.get("name", employee_id),
            "role": rep.get("role", ""),
            "department": rep.get("department", ""),
            "specialty_tags": rep.get("specialty_tags", []),
        },
        "totals": {
            "reviews": len(reports),
            "principles": len(principles_total),
            "scenarios": len(deals),
            "streak_weeks": streak,
        },
        "this_month": {
            "label": this_month,
            "reviews": reviews_month,
            "new_principles": len(principles_month),
            "active_days": active_days_month,
            "strengths": sum(1 for s in skills if s["stars"] >= 4),
        },
        "skills": skills,
        "monthly": monthly,
    }
