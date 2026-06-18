"""In-memory data store — the single source of truth for tools and front ends.

Loads the committed seed JSON once (module-level cache) and exposes small,
pure-Python query helpers. The four production tables (deals, sales_activities,
quotes, orders) mirror the real SPR schema (see Schema.md); reps/customers/
products/environments/playbook are supplementary reference data the SPR tables
reference. Everything downstream (scoring, tools, dashboard, chat) reads through
here, so the data model lives in exactly one place.
"""
from __future__ import annotations

import json
from functools import lru_cache

from senpai import config

_FILES = ["reps", "customers", "products", "environments", "playbook",
          "deals", "sales_activities", "quotes", "orders"]


@lru_cache(maxsize=1)
def _load() -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}
    for name in _FILES:
        path = config.SEED_DIR / f"{name}.json"
        data[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    return data


def reload() -> None:
    """Drop the cache (used by tests / after regenerating seed)."""
    _load.cache_clear()


# --- collections -----------------------------------------------------------
def all_deals() -> list[dict]:
    return _load()["deals"]


def all_reps() -> list[dict]:
    return _load()["reps"]


def all_customers() -> list[dict]:
    return _load()["customers"]


def all_products() -> list[dict]:
    return _load()["products"]


def all_activities() -> list[dict]:
    return _load()["sales_activities"]


def all_quotes() -> list[dict]:
    return _load()["quotes"]


def all_orders() -> list[dict]:
    return _load()["orders"]


def all_playbook() -> list[dict]:
    return _load()["playbook"]


def open_deals() -> list[dict]:
    """Live pipeline = deals whose order_rank is in the open band (2_A+ … 6_P)."""
    return [d for d in all_deals() if config.is_open_rank(d.get("order_rank"))]


# --- field accessors -------------------------------------------------------
def deal_rep_id(deal: dict) -> str:
    """Employee ID owning a deal (from sales_info)."""
    return (deal.get("sales_info") or {}).get("employee_id", "")


# --- lookups ---------------------------------------------------------------
def get_deal(deal_id: str) -> dict | None:
    return next((d for d in all_deals() if d["deal_id"] == deal_id), None)


def get_customer(customer_id: str) -> dict | None:
    return next((c for c in all_customers() if c["customer_id"] == customer_id), None)


def get_rep(employee_id: str) -> dict | None:
    return next((r for r in all_reps() if r["employee_id"] == employee_id), None)


def get_product(product_code: str) -> dict | None:
    return next((p for p in all_products() if p["product_code"] == product_code), None)


def get_environment(customer_id: str) -> dict | None:
    return next((e for e in _load()["environments"]
                 if e["customer_id"] == customer_id), None)


# --- relations -------------------------------------------------------------
def deals_for_rep(employee_id: str) -> list[dict]:
    return [d for d in all_deals() if deal_rep_id(d) == employee_id]


def deals_for_customer(customer_id: str) -> list[dict]:
    return [d for d in all_deals() if d["customer_id"] == customer_id]


def activities_for_deal(deal_id: str) -> list[dict]:
    """All sales activities for a deal, newest first (the deal's interaction log)."""
    rows = [a for a in all_activities() if a.get("deal_id") == deal_id]
    return sorted(rows, key=lambda a: a.get("activity_date", ""), reverse=True)


def daily_reports_for_rep(employee_id: str) -> list[dict]:
    """002_Daily Report activities authored by a rep."""
    return [a for a in all_activities()
            if (a.get("sales_info") or {}).get("employee_id") == employee_id
            and a.get("activity_type") == "002_Daily Report"]


def quote_for_deal(deal_id: str) -> dict | None:
    """A deal's quote, resolved via the quote_id linked on its activities."""
    qid = next((a.get("quote_id") for a in activities_for_deal(deal_id)
                if a.get("quote_id")), None)
    return next((q for q in all_quotes() if q["quote_id"] == qid), None) if qid else None


def orders_for_deal(deal_id: str) -> list[dict]:
    """Order lines for a deal, resolved via the order_id linked on its activities."""
    oids = {a.get("order_id") for a in activities_for_deal(deal_id) if a.get("order_id")}
    return [o for o in all_orders() if o["order_id"] in oids]


# --- display helpers -------------------------------------------------------
def customer_name(customer_id: str) -> str:
    c = get_customer(customer_id)
    return c["name"] if c else customer_id


def rep_name(employee_id: str) -> str:
    r = get_rep(employee_id)
    return r["name"] if r else employee_id


def find_customer_by_name(name: str) -> dict | None:
    """Loose match: exact, then substring (handles 'アクメ商事' vs '株式会社アクメ商事')."""
    if not name:
        return None
    n = name.strip()
    for c in all_customers():
        if c["name"] == n:
            return c
    for c in all_customers():
        if n in c["name"] or c["name"] in n:
            return c
    return None
