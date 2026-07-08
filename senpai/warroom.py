"""Pipeline War Room — a deterministic time-machine replay of the pipeline.

Reconstructs every deal AS OF a series of weekly snapshot dates — its order rank
from rank_history.json (the normalized rank change log), its activities filtered
to the snapshot date — and scores each reconstruction with the SAME score_deal
engine the dashboard uses, passing the snapshot date as `today`. Nothing is
interpolated or guessed: every point in the replay is the real engine run
against the data that existed on that date.

The payload is presentation-ready: one static row per deal plus a compact
per-snapshot series aligned to the shared snapshot date list. The frontend
(web/components/warroom) derives the stat tiles and the rank→outcome Sankey
client-side so its rep filter and time scrubber stay consistent with the field.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache

from senpai import config
from senpai.data import store
from senpai.health.scoring import score_deal


@lru_cache(maxsize=1)
def _rank_history() -> dict[str, list[dict]]:
    """rank_history.json grouped by deal_id, ascending by changed_at. The store
    does not load this table (nothing else reads it), so load it here."""
    path = config.SEED_DIR / "rank_history.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    by_deal: dict[str, list[dict]] = {}
    for r in rows:
        by_deal.setdefault(r.get("deal_id"), []).append(r)
    for events in by_deal.values():
        events.sort(key=lambda e: e.get("changed_at", ""))
    return by_deal


def _d(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None


def _rank_as_of(deal: dict, t: date) -> tuple[str, str | None]:
    """(rank, rank_updated_at) as of date t: the last logged change at or before
    t, else the initial rank as of registration. Overlay deals (signup demos)
    have no history and keep their current rank throughout."""
    events = _rank_history().get(deal.get("deal_id"), [])
    current: dict | None = None
    for e in events:
        changed = _d(e.get("changed_at"))
        if changed is not None and changed <= t:
            current = e
        else:
            break
    if current is not None:
        return current.get("rank"), current.get("changed_at")
    if events:  # registered but before the first logged change
        return deal.get("initial_order_rank"), deal.get("registered_at")
    return deal.get("order_rank"), deal.get("rank_updated_at")


def _status_for_rank(rank: str | None) -> str:
    if rank in config.WON_RANKS:
        return "won"
    if rank in config.DEAD_RANKS:
        return "lost"
    return "open"


# Replay horizon. The seed's full history spans years; the replay tells its
# story in the recent window (and keeps the payload demo-sized). Deals that
# closed before the window enter already-terminal, so tallies stay correct.
WINDOW_WEEKS = 26


def _snapshot_dates(deals: list[dict], today: date) -> list[date]:
    """Weekly dates from the earliest registration (capped at WINDOW_WEEKS back)
    through today (inclusive)."""
    registered = [d for deal in deals if (d := _d(deal.get("registered_at")))]
    start = min(registered) if registered else today
    start = max(start, today - timedelta(weeks=WINDOW_WEEKS))
    dates: list[date] = []
    t = start
    while t < today:
        dates.append(t)
        t += timedelta(days=7)
    dates.append(today)
    return dates


def build_warroom(manager: str | None = None) -> dict:
    """The full replay payload. `manager` (an employee_id) scopes to that
    manager's team, mirroring the dashboard's scoping; None = all deals."""
    today = config.today()
    team = store.team_of(manager) if manager else None

    deals = [d for d in store.all_deals()
             if team is None or store.deal_rep_id(d) in team]
    snapshots = _snapshot_dates(deals, today)

    rows: list[dict] = []
    for deal in deals:
        registered = _d(deal.get("registered_at"))
        acts = store.activities_for_deal(deal["deal_id"])  # newest first
        expected = _d(deal.get("expected_order_date"))
        rep_id = store.deal_rep_id(deal)
        customer = store.get_customer(deal.get("customer_id")) or {}

        series: list[dict | None] = []
        for t in snapshots:
            if registered is None or t < registered:
                series.append(None)
                continue
            rank, rank_updated = _rank_as_of(deal, t)
            status = _status_for_rank(rank)
            if status != "open":
                series.append({"st": status, "r": rank})
                continue
            # Reconstruct the deal as it stood on t and run the real engine.
            deal_t = {
                **deal,
                "order_rank": rank,
                "rank_updated_at": rank_updated,
                "days_until_order": (expected - t).days if expected else None,
            }
            acts_t = [a for a in acts
                      if (ad := _d(a.get("activity_date"))) and ad <= t]
            result = score_deal(deal_t, acts_t, today=t)
            series.append({"st": "open", "s": result.score, "b": result.band,
                           "r": rank})

        rows.append({
            "deal_id": deal["deal_id"],
            "deal_name": deal.get("deal_name", deal["deal_id"]),
            "customer": customer.get("name", deal.get("customer_id", "")),
            "customer_id": deal.get("customer_id", ""),
            "rep_id": rep_id,
            "rep_name": store.rep_name(rep_id),
            "amount": deal.get("amount") or deal.get("total_order_amount") or 0,
            "expected_order_date": deal.get("expected_order_date"),
            "registered_at": deal.get("registered_at"),
            "initial_rank": deal.get("initial_order_rank") or deal.get("order_rank"),
            "outcome": _status_for_rank(deal.get("order_rank")),
            "series": series,
        })

    return {
        "as_of": today.isoformat(),
        "snapshots": [t.isoformat() for t in snapshots],
        "thresholds": {"yellow": config.YELLOW_THRESHOLD, "red": config.RED_THRESHOLD},
        "deals": rows,
    }
