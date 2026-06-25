"""Rep coaching progress — is the rep getting better over time?

Recomputes a rep's coaching weaknesses **as of** each of the last few fiscal years
(scoring only the deals/activities that existed by that cut-off) to produce a
per-issue trend, and joins the coaching threads to report whether past coaching was
acted on. Pure replay over the deterministic engine — no new model, no prediction.

A rep flagged "improving" in the data generator (their notes get more complete over
fiscal years) will visibly trend down here; that is the signal a manager wants when
deciding whether coaching is landing.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from senpai import config
from senpai.coaching import compute_issues
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal

# Themes worth trending: note-quality / skill issues the rep controls. We omit
# long_inactivity here because the historical replay scores each deal at its last
# in-window activity (see below), so staleness is not a meaningful trend signal.
_TRACK = ["missing_decision_maker", "weak_customer_discovery",
          "premature_discount", "repeated_unresolved"]


def _fy(d_iso: str) -> int:
    """Japanese fiscal year (April start) of a YYYY-MM-DD date."""
    y, m = int(d_iso[:4]), int(d_iso[5:7])
    return y if m >= 4 else y - 1


def _fy_end(fy: int) -> date:
    """Last day of fiscal year `fy` (31 March of the next calendar year)."""
    return date(fy + 1, 3, 31)


def rep_progress(employee_id: str, today: date | None = None,
                 windows: int = 4) -> dict:
    """Per-fiscal-year weakness rates for a rep, with per-issue trend + acted-on."""
    today = today or config.today()
    rep = store.get_rep(employee_id)
    deals = store.deals_for_rep(employee_id)
    acts_by_deal = {d["deal_id"]: store.activities_for_deal(d["deal_id"]) for d in deals}

    ref_fy = _fy(today.isoformat())
    fys = list(range(ref_fy - windows + 1, ref_fy + 1))    # ascending

    series: list[dict] = []
    for fy in fys:
        cutoff = min(today, _fy_end(fy))
        cut_iso = cutoff.isoformat()
        weak = Counter()
        active = 0
        for d in deals:
            # activities that existed by the cut-off
            acts = [a for a in acts_by_deal[d["deal_id"]]
                    if a.get("activity_date", "") <= cut_iso]
            if not acts:
                continue
            # "active in this FY" = had an activity during that fiscal year
            if not any(_fy(a["activity_date"]) == fy for a in acts):
                continue
            active += 1
            # Score the deal as of its LAST in-window activity, not the FY end, so
            # the trend reflects note-quality skill issues (decision-maker, discovery,
            # discounting) rather than the staleness any old deal shows at FY end.
            eval_iso = max(a["activity_date"] for a in acts)
            eval_date = date.fromisoformat(eval_iso)
            res = score_deal(d, acts, today=eval_date)
            flags = deal_flags(d, acts, health_band=res.band, today=eval_date)
            for it in compute_issues(d, acts, res, flags, eval_date):
                if it["issue"] in _TRACK:
                    weak[it["issue"]] += 1
        per_deal = round(sum(weak.values()) / active, 2) if active else 0.0
        series.append({
            "window": f"FY{fy}", "active_deals": active,
            "weaknesses_per_deal": per_deal,
            "by_issue": {k: weak.get(k, 0) for k in _TRACK if weak.get(k)},
        })

    # Per-issue trend: first vs last window with any active deals.
    populated = [s for s in series if s["active_deals"]]
    trends: dict[str, str] = {}
    if len(populated) >= 2:
        first, last = populated[0], populated[-1]
        for issue in _TRACK:
            fr = first["by_issue"].get(issue, 0) / max(first["active_deals"], 1)
            lr = last["by_issue"].get(issue, 0) / max(last["active_deals"], 1)
            trends[issue] = ("improving" if lr < fr - 0.05
                             else "worsening" if lr > fr + 0.05 else "flat")
        overall = (last["weaknesses_per_deal"] - first["weaknesses_per_deal"])
        headline = ("改善傾向" if overall < -0.1 else "悪化傾向" if overall > 0.1 else "横ばい")
    else:
        headline = "データ不足"

    threads = store.coaching_threads_for_rep(employee_id)
    resolved = sum(1 for t in threads if t.get("status") == "resolved")

    return {
        "employee_id": employee_id,
        "name": rep.get("name") if rep else employee_id,
        "windows": [s["window"] for s in series],
        "series": series,
        "trends": trends,
        "headline": headline,
        "coaching_acted_on": {
            "total": len(threads), "resolved": resolved,
            "rate": round(resolved / len(threads), 2) if threads else None,
        },
    }
