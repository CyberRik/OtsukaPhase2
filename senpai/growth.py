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

from collections import Counter
from datetime import date, timedelta

from senpai import config
from senpai.data import store
from senpai.knowledge import store as kstore

# The five skills we surface, each derived from a transparent signal below.
SKILL_KEYS = [
    "relationship_building",
    "decision_maker_discovery",
    "customer_discovery",
    "closing_discipline",
    "proposal_pricing",
]


def junior_reps() -> list[dict]:
    """Reps whose role is junior — the audience of the Motivation portal."""
    return [r for r in store.all_reps() if r.get("role") == "junior"]


def _rep_activities(employee_id: str) -> list[dict]:
    return [a for a in store.all_activities()
            if (a.get("sales_info") or {}).get("employee_id") == employee_id]


def _stars(ratio: float) -> int:
    """Map a 0..1 signal to a 1..5 star rating (never 0 — everyone's on the path)."""
    return max(1, min(5, round(1 + ratio * 4)))


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _skills(rep: dict, deals: list[dict], acts: list[dict]) -> list[dict]:
    n_deals = len(deals)
    n_acts = len(acts)

    # Decision-maker discovery: share of deals where a decision-maker title shows
    # up on a business card in the activity log.
    dm_deals = 0
    for d in deals:
        dacts = store.activities_for_deal(d["deal_id"])
        if any(any(t in (a.get("business_card_info") or "") for t in config.DECISION_MAKER_TITLES)
               for a in dacts):
            dm_deals += 1
    dm_ratio = dm_deals / n_deals if n_deals else 0.0

    # Customer discovery: share of activities that captured a customer challenge.
    disc_ratio = (sum(1 for a in acts if a.get("customer_challenge")) / n_acts) if n_acts else 0.0

    # Relationship building: depth of engagement (avg touches per deal, capped at 5).
    depth = (n_acts / n_deals) if n_deals else 0.0
    rel_ratio = min(1.0, depth / 5.0)

    # Closing discipline: win rate among the rep's *closed* deals.
    closed = [d for d in deals if d.get("order_rank") in (config.WON_RANKS | config.DEAD_RANKS)]
    won = [d for d in closed if d.get("order_rank") in config.WON_RANKS]
    win_ratio = (len(won) / len(closed)) if closed else 0.5

    # Proposal & pricing: share of deals that reached a quote.
    quoted = sum(1 for d in deals if store.quote_for_deal(d["deal_id"]))
    quote_ratio = (quoted / n_deals) if n_deals else 0.0

    ratios = {
        "relationship_building": rel_ratio,
        "decision_maker_discovery": dm_ratio,
        "customer_discovery": disc_ratio,
        "closing_discipline": win_ratio,
        "proposal_pricing": quote_ratio,
    }
    return [{"key": k, "stars": _stars(ratios[k])} for k in SKILL_KEYS]


# Presence cues per principle tag: a topic is "touched" when the rep's own
# reports talk about it. These mirror the vocabulary the Review Coach reasons
# over, so "principles learned" reflects the situations the rep has actually
# worked through — not literal tag strings (which rarely appear in prose).
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
    "関係構築": ["関係", "信頼", "雑談", "距離", "懇親"],
    "情報確認": ["環境", "構成", "確認", "現状", "ネットワーク"],
    "移行": ["移行", "乗り換え", "リプレース", "入れ替え"],
    "案件管理": ["案件", "進捗", "フォロー", "次回"],
    "交渉": ["交渉", "条件", "折衝", "調整"],
    "ステークホルダー": ["関係者", "部署", "利害", "現場"],
}


def _principles_touched(rep: dict, acts: list[dict], month: str | None = None) -> list[str]:
    """Approved principles whose subject matter shows up in the rep's reports and
    logged challenges (optionally limited to one YYYY-MM). A principle counts as
    'touched' when any cue for one of its tags appears in that text."""
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


def rep_growth(employee_id: str, today: date | None = None) -> dict:
    today = today or config.today()
    rep = store.get_rep(employee_id) or {}
    deals = store.deals_for_rep(employee_id)
    acts = _rep_activities(employee_id)
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

    # Monthly activity for the trailing six months (oldest → newest).
    per_month = Counter((a.get("activity_date") or "")[:7] for a in acts if a.get("activity_date"))
    monthly = []
    y, m = today.year, today.month
    for i in range(5, -1, -1):
        yy, mm = y, m - i
        while mm <= 0:
            mm += 12
            yy -= 1
        key = f"{yy:04d}-{mm:02d}"
        monthly.append({"month": key, "count": per_month.get(key, 0)})

    skills = _skills(rep, deals, acts)
    principles_total = _principles_touched(rep, acts)
    principles_month = _principles_touched(rep, acts, month=this_month)
    reviews_month = sum(1 for a in reports if (a.get("activity_date") or "")[:7] == this_month)
    active_days_month = len({a.get("activity_date") for a in acts
                             if (a.get("activity_date") or "")[:7] == this_month and a.get("activity_date")})

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
