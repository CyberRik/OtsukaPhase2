"""Deterministic deal-health scoring — the trustworthy core.

Pure Python, rank-aware, fully explainable. Produces a 0–100 *risk* score (higher
= worse) as the sum of independent signal contributions, plus a red/yellow/green
band. Every signal carries a human-readable Japanese `reason`, so nothing is a
black box and no number is ever invented by a model.

Reads the real SPR fields directly (see Schema.md): a deal row plus its
`sales_activities` (newest first). All thresholds live in senpai.config
(RANK_BENCHMARKS, STALL_LEXICON, decision-maker titles, band cutoffs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from senpai import config


@dataclass
class Signal:
    name: str
    points: int
    reason: str   # Japanese, manager-facing


@dataclass
class HealthResult:
    score: int
    band: str                       # 'red' | 'yellow' | 'green'
    signals: list[Signal] = field(default_factory=list)

    def top_reasons(self, n: int = 3) -> list[str]:
        ordered = sorted(self.signals, key=lambda s: s.points, reverse=True)
        return [s.reason for s in ordered[:n]]


def _d(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _has_decision_maker(activities: list[dict]) -> bool:
    """Any activity whose business_card_info carries a decision-maker title."""
    for a in activities:
        card = a.get("business_card_info") or ""
        if any(title in card for title in config.DECISION_MAKER_TITLES):
            return True
    return False


def score_deal(deal: dict, activities: list[dict] | None = None,
               today: date | None = None) -> HealthResult:
    """Score one deal. `activities` are that deal's sales_activities (newest first);
    if omitted, activity-based signals are simply skipped."""
    today = today or config.today()
    activities = activities or []
    rank = deal.get("order_rank")
    max_days, cadence = config.RANK_BENCHMARKS.get(rank, (45, 14))
    signals: list[Signal] = []

    # Latest activity date = the deal's last contact.
    act_dates = sorted((d for a in activities if (d := _d(a.get("activity_date")))),
                       reverse=True)
    last = act_dates[0] if act_dates else None

    # 1. Staleness — days since last activity vs the rank's expected cadence.
    if last is not None:
        stale = (today - last).days
        if stale > 2 * cadence:
            signals.append(Signal("staleness", 30,
                                  f"{stale}日間接触なし(目安{cadence}日の2倍超)"))
        elif stale > cadence:
            signals.append(Signal("staleness", 15,
                                  f"{stale}日間接触なし(目安{cadence}日超)"))

    # 2. Rank stagnation — days at the current rank beyond the benchmark (scaled).
    updated = _d(deal.get("rank_updated_at"))
    if updated is not None:
        in_rank = (today - updated).days
        if in_rank > max_days:
            pts = min(25, round((in_rank - max_days) / max_days * 25))
            if pts > 0:
                signals.append(Signal("rank_age", pts,
                                      f"{rank}に{in_rank}日滞留(目安{max_days}日)"))

    # 3. Expected order date already past while still open.
    until = deal.get("days_until_order")
    expected = _d(deal.get("expected_order_date"))
    past = (until is not None and until < 0) or (expected is not None and expected < today)
    if past and config.is_open_rank(rank):
        label = expected.isoformat() if expected else "予定日"
        signals.append(Signal("order_date_past", 25,
                              f"完了予定日({label})を過ぎても未受注"))

    # 4. Rank regression — current rank weaker than the rank first assigned.
    init = deal.get("initial_order_rank")
    if init and config.rank_num(rank) > config.rank_num(init):
        drop = config.rank_num(rank) - config.rank_num(init)
        signals.append(Signal("rank_regression", min(20, drop * 10),
                              f"ランクが {init} → {rank} に低下"))

    # 5. Missing decision-maker at a strong rank.
    if rank in config.DECISION_MAKER_RANKS and not _has_decision_maker(activities):
        signals.append(Signal("missing_dm", 15, "決裁者が未特定"))

    # 6. Stall language in the latest daily_report.
    if activities:
        latest_text = activities[0].get("daily_report", "")
        hit = next((w for w in config.STALL_LEXICON if w in latest_text), None)
        if hit:
            signals.append(Signal("stall_language", 10,
                                  f"直近の日報に停滞サイン「{hit}」"))

    # 7. Low activity — nothing logged in the last 30 days.
    recent = [d for d in act_dates if (today - d).days <= 30]
    if not recent:
        signals.append(Signal("low_activity", 10, "直近30日の活動が0件"))

    score = min(100, sum(s.points for s in signals))
    return HealthResult(score=score, band=config.band_for_score(score), signals=signals)
