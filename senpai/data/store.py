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


@lru_cache(maxsize=1)
def customer_aliases() -> dict[str, list[str]]:
    """English / romaji / known-alias forms per customer_id (customer_aliases.json).
    Keys starting with '_' (e.g. '_comment') are metadata and skipped."""
    path = config.SEED_DIR / "customer_aliases.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, list)}


def reload() -> None:
    """Drop the cache (used by tests / after regenerating seed)."""
    _load.cache_clear()
    customer_aliases.cache_clear()
    _alias_index.cache_clear()


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


# --- backward-compat shims (for the friend-owned web-app / coach experiment) ---
# Our pipeline reads sales_activities directly; the experiment still calls the old
# notes/report API. These derive old-shaped data from sales_activities so that code
# keeps working unchanged. They are NOT used by our pipeline.
def notes_for_deal(deal_id: str) -> list[dict]:
    """Old 'notes' shape, derived from sales_activities (newest first). Each row
    carries both the new keys and the legacy aliases (date/text/channel/rep_id)."""
    out = []
    for a in activities_for_deal(deal_id):
        out.append({**a,
                    "date": a.get("activity_date"),
                    "text": a.get("daily_report"),
                    "channel": a.get("activity_type"),
                    "rep_id": (a.get("sales_info") or {}).get("employee_id")})
    return out


def report_for_deal(deal_id: str) -> dict | None:
    """No standalone report object exists in the SPR schema (daily_report lives on
    activities). Returned as None for compat; callers tolerate it."""
    return None


def reports_for_rep(employee_id: str) -> list[dict]:
    """Compat alias — daily-report activities for a rep."""
    return daily_reports_for_rep(employee_id)


def find_customer_by_name(name: str) -> dict | None:
    """Loose JA match: exact, then substring (handles 'アクメ商事' vs '株式会社アクメ商事').
    For cross-language resolution (English/romaji/alias) use resolve_customer."""
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


# --- alias-aware customer resolution ---------------------------------------
# Resolves Japanese, English, romaji and known-alias forms to the canonical
# customer record — BEFORE any retrieval. Built so a name that maps to more than
# one customer is treated as ambiguous and never guessed (we'd rather miss than
# fabricate the wrong customer's facts).
_CORP_TOKENS = ["株式会社", "有限会社", "合同会社", "(株)", "（株）", "(有)", "（有）"]


def _norm(s: str) -> str:
    """Case/space-insensitive key. JA text is unaffected by lower()."""
    return " ".join((s or "").split()).lower()


def name_forms(name: str) -> list[str]:
    """A customer name plus its bare form (corporate prefix/suffix removed), so
    '有限会社村田印刷' is found from text that just says '村田印刷'."""
    forms = {name}
    bare = name
    for tok in _CORP_TOKENS:
        bare = bare.replace(tok, "")
    bare = bare.strip()
    if len(bare) >= 2:
        forms.add(bare)
    return [f for f in forms if f]


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, set[str]]:
    """Map a normalized name/alias key -> set of customer_ids that answer to it.
    A key owned by >1 customer is ambiguous (callers must not guess)."""
    aliases = customer_aliases()
    idx: dict[str, set[str]] = {}
    for c in all_customers():
        cid = c["customer_id"]
        keys = set(name_forms(c.get("name", ""))) | set(aliases.get(cid, []))
        for k in keys:
            kk = _norm(k)
            if len(kk) >= 2:
                idx.setdefault(kk, set()).add(cid)
    return idx


def resolve_customer(query: str) -> dict | None:
    """Resolve a customer from an id, JA name, English/romaji name or known alias.
    Returns None when the query is empty, unknown, or ambiguous (maps to >1
    customer) — never a guess. This is the single entry point tools and the coach
    use before retrieval."""
    if not query:
        return None
    q = query.strip()
    by_id = get_customer(q)
    if by_id:
        return by_id
    ids = _alias_index().get(_norm(q))
    if ids:
        return get_customer(next(iter(ids))) if len(ids) == 1 else None
    # Fall back to loose JA substring match (legacy behaviour) for partial JA names.
    return find_customer_by_name(q)


def match_customer_in_text(text: str) -> dict | None:
    """Find the customer named anywhere in free text — across JA, English, romaji
    and alias forms. Longest match wins (so 'Aozora Services' beats 'Aozora', and
    '大和商事システム' beats '大和'); an ambiguous winning form resolves to None so
    we never attribute the wrong customer's history."""
    low = (text or "").lower()
    best: tuple[int, set[str]] | None = None
    for key, ids in _alias_index().items():
        if key in low and (best is None or len(key) > best[0]):
            best = (len(key), ids)
    if best and len(best[1]) == 1:
        return get_customer(next(iter(best[1])))
    return None
