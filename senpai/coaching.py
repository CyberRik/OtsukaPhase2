"""Manager coaching workspace — Pillar: Coaching / Visibility.

A read-only aggregation over the SAME deterministic engines the dashboard uses
(`score_deal`, `deal_flags`). It answers a manager's daily question — "where
should I spend my coaching time today?" — with four grounded views:

  1. needs_coaching  — a ranked queue of deals with the single coaching issue
                       that matters most for each, and a transparent reason.
  2. trends          — the most common coaching themes across the team, with a
                       direction derived from real rank movement.
  3. confidence      — Confidence vs Reality: the rep's expressed confidence (the
                       order_rank itself) checked against observed signals.
  4. summary         — a simple weekly digest.

No new scores, no prediction, no LLM. Every issue maps to a rule a manager can
read off the data. Reason text is returned as a key + params so the frontend can
render it natively in either language.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from senpai import config
from senpai.coach.explainability import explain_coaching_issue
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import _d, _has_decision_maker, score_deal

# Coaching issues, in the priority order used to pick a deal's headline issue.
ISSUE_PRIORITY: dict[str, str] = {
    "confidence_mismatch": "high",
    "missing_decision_maker": "high",
    "long_inactivity": "high",
    "premature_discount": "medium",
    "repeated_unresolved": "medium",
    "weak_customer_discovery": "medium",
    "incomplete_reports": "low",
}
_ORDER = list(ISSUE_PRIORITY)
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _discount_rate(deal: dict) -> float:
    rates = []
    q = store.quote_for_deal(deal["deal_id"])
    if q:
        rates.append(q.get("discount_rate") or 0)
    rates += [o.get("discount_rate") or 0 for o in store.orders_for_deal(deal["deal_id"])]
    return max(rates) if rates else 0


def _confidence(rank: str | None) -> str:
    """The rep's expressed confidence = the order_rank band they assigned."""
    n = config.rank_num(rank)
    if n <= 2:
        return "high"
    if n <= 4:
        return "moderate"
    return "low"


def compute_issues(deal: dict, acts: list[dict], res, flags, today: date) -> list[dict]:
    """All coaching issues that fire for a deal (deterministic rules). Public entry
    point reused by the rep-coaching profile (senpai.coach.profile)."""
    return _issues(deal, acts, res, flags, today)


def _issues(deal: dict, acts: list[dict], res, flags, today: date) -> list[dict]:
    """All coaching issues that fire for a deal (deterministic rules)."""
    rank = deal.get("order_rank")
    fnames = {f.name for f in flags}
    act_dates = sorted((d for a in acts if (d := _d(a.get("activity_date")))), reverse=True)
    last = act_dates[0] if act_dates else None
    out: list[dict] = []

    if "optimism_mismatch" in fnames:
        out.append({"issue": "confidence_mismatch", "params": {"rank": rank or "-"}})

    if rank in config.DECISION_MAKER_RANKS and not _has_decision_maker(acts):
        reports = sum(1 for a in acts if a.get("daily_report"))
        out.append({"issue": "missing_decision_maker", "params": {"reports": reports}})

    if last is not None and (today - last).days > 30:
        out.append({"issue": "long_inactivity", "params": {"days": (today - last).days}})
    elif not act_dates:
        out.append({"issue": "long_inactivity", "params": {"days": 0}})

    disc = _discount_rate(deal)
    if disc > 10 and (not _has_decision_maker(acts) or config.rank_num(rank) >= 4):
        out.append({"issue": "premature_discount", "params": {"rate": round(disc)}})

    init = deal.get("initial_order_rank")
    if init and config.rank_num(rank) > config.rank_num(init):
        out.append({"issue": "repeated_unresolved", "params": {"init": init, "rank": rank or "-"}})

    n = len(acts)
    filled = sum(1 for a in acts if a.get("customer_challenge"))
    if n >= 3 and filled / n < 0.34:
        out.append({"issue": "weak_customer_discovery", "params": {"filled": filled, "total": n}})

    if "missing_fields" in fnames:
        out.append({"issue": "incomplete_reports", "params": {}})

    return out


def _confidence_vs_reality(deal, acts, res, today, rep, customer) -> dict:
    rank = deal.get("order_rank")
    conf = _confidence(rank)
    act_dates = sorted((d for a in acts if (d := _d(a.get("activity_date")))), reverse=True)
    quote = store.quote_for_deal(deal["deal_id"]) is not None
    dm = _has_decision_maker(acts)
    recent = any((today - d).days <= 30 for d in act_dates)
    positives = sum([quote, dm, recent])
    overconfident = conf == "high" and (res.band == "red" or positives <= 1)
    return {
        "deal_id": deal["deal_id"], "rep": rep, "customer": customer,
        "confidence": conf, "band": res.band, "score": res.score,
        "status": "mismatch" if overconfident else "supported",
        "positives": positives,
        "signals": [
            {"key": "quote", "positive": quote},
            {"key": "decision_maker", "positive": dm},
            {"key": "recent_activity", "positive": recent},
        ],
    }


def coaching_workspace(today: date | None = None) -> dict:
    today = today or config.today()
    cards: list[dict] = []
    issue_counter: Counter = Counter()
    issue_reps: dict[str, set] = {}
    issue_deals: dict[str, list] = {}
    confvr: list[dict] = []
    flagged_deals = 0
    improving = 0

    for deal in store.open_deals():
        acts = store.activities_for_deal(deal["deal_id"])
        res = score_deal(deal, acts, today=today)
        flags = deal_flags(deal, acts, res.band, today=today)
        rep = store.rep_name(store.deal_rep_id(deal))
        customer = store.customer_name(deal["customer_id"])

        init = deal.get("initial_order_rank")
        if init and config.rank_num(deal.get("order_rank")) < config.rank_num(init):
            improving += 1

        issues = _issues(deal, acts, res, flags, today)
        if issues:
            flagged_deals += 1
        for it in issues:
            key = it["issue"]
            issue_counter[key] += 1
            issue_reps.setdefault(key, set()).add(rep)
            issue_deals.setdefault(key, []).append(deal)

        # Headline issue for the queue card: highest priority, then declared order.
        if issues:
            top = min(issues, key=lambda i: (_PRIORITY_RANK[ISSUE_PRIORITY[i["issue"]]], _ORDER.index(i["issue"])))
            explanation = explain_coaching_issue(
                issue_key=top["issue"],
                params=top["params"],
                deal=deal,
                activities=acts,
                today=today,
            )
            cards.append({
                "deal_id": deal["deal_id"], "rep": rep,
                "employee_id": store.deal_rep_id(deal), "customer": customer,
                "issue": top["issue"], "priority": ISSUE_PRIORITY[top["issue"]],
                "params": top["params"], "band": res.band, "score": res.score,
                "n_issues": len(issues),
                "explanation": explanation.to_dict(),
            })

        confvr.append(_confidence_vs_reality(deal, acts, res, today, rep, customer))

    cards.sort(key=lambda c: (_PRIORITY_RANK[c["priority"]], -c["score"]))

    # Trends — direction from real rank movement among each issue's deals.
    trends = []
    for key, count in issue_counter.most_common():
        affected = issue_deals.get(key, [])
        reg = sum(1 for d in affected
                  if d.get("initial_order_rank")
                  and config.rank_num(d.get("order_rank")) > config.rank_num(d.get("initial_order_rank")))
        imp = sum(1 for d in affected
                  if d.get("initial_order_rank")
                  and config.rank_num(d.get("order_rank")) < config.rank_num(d.get("initial_order_rank")))
        trend = "up" if reg > imp else "down" if imp > reg else "flat"
        trends.append({
            "issue": key, "count": count, "trend": trend,
            "reps": sorted(issue_reps.get(key, set())),
        })

    # Confidence vs Reality — mismatches first, a few supported as contrast.
    mismatches = sorted((c for c in confvr if c["status"] == "mismatch"),
                        key=lambda c: -c["score"])
    supported = sorted((c for c in confvr if c["status"] == "supported" and c["positives"] >= 2
                        and c["band"] != "red"), key=lambda c: -c["positives"])
    confidence = mismatches[:5] + supported[:3]

    summary = {
        "reps_need_coaching": len({c["employee_id"] for c in cards}),
        "opportunities_flagged": flagged_deals,
        "top_issue": trends[0]["issue"] if trends else None,
        "improving": improving,
    }

    return {
        "needs_coaching": cards,
        "trends": trends,
        "confidence": confidence,
        "summary": summary,
    }
