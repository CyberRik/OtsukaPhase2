"""Structured shaping of store records — byte-for-byte replicas of the server's
research helpers (`_deal_summary`, `_activity_summary`, `_public_customer`,
`_products_for_deals`), split so deal *facts* and deal *health* can be produced by
separate capabilities (CRM vs Health) and re-merged into the identical summary.

`deal_summary(d, today) == {**deal_facts(d), "health": health_read(d, today)}` is
exactly the legacy `_deal_summary(d)`. Parity is enforced by the golden tests.
"""
from __future__ import annotations

from senpai.data import store
from senpai.health.scoring import score_deal


def deal_facts(d: dict) -> dict:
    """Everything in the legacy `_deal_summary` EXCEPT the health block (which the
    Health capability supplies, so it can depend on CRM/SimilarDeals)."""
    return {
        "deal_id": d["deal_id"],
        "customer": store.customer_name(d["customer_id"]),
        "rep": store.rep_name(store.deal_rep_id(d)),
        "stage": d.get("order_rank"),
        "amount": d.get("total_order_amount"),
        "expected_close_date": d.get("expected_order_date"),
        "product_category": d.get("product_category"),
    }


def health_read(d: dict, today) -> dict:
    """The health block of the legacy `_deal_summary` — scored exactly as before."""
    res = score_deal(d, store.activities_for_deal(d["deal_id"]), today=today)
    return {"band": res.band, "score": res.score, "reasons": res.top_reasons(3)}


def deal_summary(d: dict, today) -> dict:
    """The full legacy `_deal_summary(d)` reconstructed from its two halves."""
    return {**deal_facts(d), "health": health_read(d, today)}


def activity_summary(a: dict) -> dict:
    return {
        "deal_id": a.get("deal_id"),
        "date": a.get("activity_date"),
        "type": a.get("activity_type"),
        "contact": a.get("business_card_info"),
        "text": a.get("daily_report"),
    }


def public_customer(c: dict | None) -> dict | None:
    if not c:
        return None
    return {"customer_id": c.get("customer_id"), "name": c.get("name"),
            "industry": c.get("industry"), "size": c.get("size"),
            "profile_tags": c.get("profile_tags", [])}


def products_for_deals(deals: list[dict]) -> list[dict]:
    categories = {d.get("product_category") for d in deals if d.get("product_category")}
    products: list[dict] = []
    seen: set[str] = set()
    for p in store.all_products():
        hay = " ".join(str(p.get(k, "")) for k in
                       ("product_name", "major", "mid", "minor", "product_code"))
        if any(cat and (cat in hay or hay in cat) for cat in categories):
            if p["product_code"] not in seen:
                seen.add(p["product_code"])
                products.append(p)
    return products
