"""Faceted search over past/current deals — the structured, grounded complement
to semantic note search.

This filters the **real SPR fields** that exist in the seed (no invented
attributes): a deal's `product_category` / `order_rank` / `total_order_amount` /
`products`, joined to its customer's `industry` / `size` / `profile_tags`. The
logical outcome (won / lost / open) is derived from the rank model in
`config` (WON_RANKS / DEAD_RANKS / OPEN_RANKS), not guessed.

Everything is a pure read over `senpai.data.store`, so a result can never be
hallucinated — the model gets exactly the rows that match the filters. The valid
facet *values* are discovered from the data via `deal_facets()`, so callers
filter by what actually exists instead of guessing field values.
"""
from __future__ import annotations

from senpai import config
from senpai.data import store

# Logical outcome → predicate on a deal's order_rank (uses the config rank model).
_OUTCOME = {
    "won": lambda rank: rank in config.WON_RANKS,
    "lost": lambda rank: rank in config.DEAD_RANKS,
    "open": lambda rank: config.is_open_rank(rank),
}


def deal_facets() -> dict[str, list[str]]:
    """The distinct facet values actually present in the seed, so a caller (or the
    model) filters by real values instead of inventing them."""
    cats: set[str] = set()
    ranks: set[str] = set()
    inds: set[str] = set()
    sizes: set[str] = set()
    tags: set[str] = set()
    for d in store.all_deals():
        if d.get("product_category"):
            cats.add(d["product_category"])
        if d.get("order_rank"):
            ranks.add(d["order_rank"])
    for c in store.all_customers():
        if c.get("industry"):
            inds.add(c["industry"])
        if c.get("size"):
            sizes.add(c["size"])
        for t in c.get("profile_tags", []) or []:
            tags.add(t)
    return {
        "product_category": sorted(cats),
        "order_rank": sorted(ranks),
        "industry": sorted(inds),
        "size": sorted(sizes),
        "profile_tags": sorted(tags),
        "outcome": list(_OUTCOME),
    }


def _matches(value, flt: str) -> bool:
    """Tolerant match: empty filter passes; otherwise case-insensitive substring
    (so '製造' matches '製造業', 'server' matches 'Server', etc.)."""
    if not flt:
        return True
    return str(flt).strip().lower() in str(value).lower()


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def find_deals(product_category: str = "", industry: str = "", size: str = "",
               outcome: str = "", order_rank: str = "",
               profile_tags: list[str] | None = None,
               min_amount=None, max_amount=None, product_code: str = "",
               limit: int = 10) -> list[dict]:
    """Return deals matching every supplied facet (unsupplied facets are ignored).

    Joins each deal to its customer for the industry/size/profile_tags facets.
    Ranked by deal value (largest first) so the most informative reference deals
    surface first; deterministic id tie-break. `limit<=0` returns all matches.
    """
    profile_tags = [t.strip() for t in (profile_tags or []) if t and t.strip()]
    out_pred = _OUTCOME.get(outcome.strip().lower()) if outcome else None
    lo, hi = _to_float(min_amount), _to_float(max_amount)
    want_code = product_code.strip().upper() if product_code else ""

    results: list[dict] = []
    for d in store.all_deals():
        rank = d.get("order_rank")
        if not _matches(d.get("product_category", ""), product_category):
            continue
        if order_rank and not _matches(rank, order_rank):
            continue
        if out_pred and not out_pred(rank):
            continue
        amt = d.get("total_order_amount", 0) or 0
        if lo is not None and amt < lo:
            continue
        if hi is not None and amt > hi:
            continue
        if want_code and want_code not in [str(p).upper() for p in d.get("products", []) or []]:
            continue

        cust = store.get_customer(d["customer_id"]) or {}
        if industry and not _matches(cust.get("industry", ""), industry):
            continue
        if size and not _matches(cust.get("size", ""), size):
            continue
        if profile_tags and not (set(profile_tags) & set(cust.get("profile_tags", []) or [])):
            continue

        results.append(d)

    results.sort(key=lambda d: (d.get("total_order_amount", 0) or 0, d["deal_id"]),
                 reverse=True)
    return results[:limit] if limit and limit > 0 else results


def outcome_breakdown(deals: list[dict]) -> dict[str, int]:
    """Win/lost/open counts over a set of deals (from the config rank model)."""
    counts = {"won": 0, "lost": 0, "open": 0, "other": 0}
    for d in deals:
        rank = d.get("order_rank")
        if rank in config.WON_RANKS:
            counts["won"] += 1
        elif rank in config.DEAD_RANKS:
            counts["lost"] += 1
        elif config.is_open_rank(rank):
            counts["open"] += 1
        else:
            counts["other"] += 1
    return counts
