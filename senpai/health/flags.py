"""Report-reliability flags — the 'is this deal real?' engine.

Each flag is an independent check that fires only when its specific condition is
met, returning a Flag with a severity and a Japanese message. These power the
manager dashboard's reliability panel and the report tools: they surface deals
whose recorded rank/status quietly contradicts their actual activity signals.

Reads the real SPR fields directly (see Schema.md): a deal row + its
sales_activities (newest first).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from senpai import config
from senpai.health.scoring import _d, _has_decision_maker


@dataclass
class Flag:
    name: str
    severity: str    # 'high' | 'medium' | 'low'
    message: str     # Japanese, manager-facing


def deal_flags(deal: dict, activities: list[dict] | None = None,
               report: dict | None = None, health_band: str | None = None,
               today: date | None = None) -> list[Flag]:
    """Return all reliability flags that fire for a deal. `health_band` (from
    scoring) drives the optimism-mismatch check.

    `report` is accepted but unused — it exists only for backward compatibility
    with the friend-owned web-app/coach experiment, whose callers pass a report
    object positionally (deal, activities, report, health_band, today). Our own
    callers pass `health_band=` by keyword and omit `report`."""
    del report   # intentionally unused (compat slot)
    today = today or config.today()
    activities = activities or []
    flags: list[Flag] = []
    rank = deal.get("order_rank")
    is_open = config.is_open_rank(rank)

    act_dates = sorted((d for a in activities if (d := _d(a.get("activity_date")))),
                       reverse=True)
    last = act_dates[0] if act_dates else None

    # close_date_passed — expected order date in the past, deal still open.
    until = deal.get("days_until_order")
    expected = _d(deal.get("expected_order_date"))
    past = (until is not None and until < 0) or (expected is not None and expected < today)
    if is_open and past:
        label = expected.isoformat() if expected else "予定日"
        flags.append(Flag("close_date_passed", "high",
                          f"完了予定日({label})を過ぎても案件がオープン"))

    # stale_active — no activity > 30 days but still marked active.
    if is_open and last is not None and (today - last).days > 30:
        flags.append(Flag("stale_active", "high",
                          f"{(today - last).days}日活動がないままアクティブ扱い"))

    # missing_fields — key fields empty (decision-maker / order date / daily report / amount).
    missing = []
    if not _has_decision_maker(activities):
        missing.append("決裁者")
    if not deal.get("total_order_amount"):
        missing.append("金額")
    if not deal.get("expected_order_date"):
        missing.append("完了予定日")
    if not any(a.get("daily_report") for a in activities):
        missing.append("日報")
    if missing:
        flags.append(Flag("missing_fields", "medium",
                          "必須項目が未入力: " + "・".join(missing)))

    # optimism_mismatch — rep keeps a strong rank but health is red.
    if rank in config.OPTIMISTIC_RANKS and health_band == "red":
        flags.append(Flag("optimism_mismatch", "high",
                          f"ランクは『{rank}』だが健全度は赤"))

    # unsupported_rank — rank updated with no daily_report activity near that date.
    updated = _d(deal.get("rank_updated_at"))
    if updated is not None:
        supported = any((ad := _d(a.get("activity_date"))) and abs((ad - updated).days) <= 3
                        for a in activities if a.get("daily_report"))
        if not supported:
            flags.append(Flag("unsupported_rank", "low",
                              f"{rank}への更新を裏づける日報がない"))

    return flags
