"""Deterministic document context — the grounded backbone for generate_proposal /
generate_ringisho.

Assembles, from the store + scoring engine ONLY, everything a grounded sales
document needs: the customer, the deal, its pain points (SPR customer_challenge /
daily reports), the matched catalog products, the real financials, comparable deals,
and the health read. No numbers are invented — every figure is copied from an SPR
field. The persuasive prose is layered on separately in narrative.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from senpai import config
from senpai.data import store
from senpai.health.scoring import score_deal
from senpai.retrieval.playbook import find_similar_deals

_OUTCOME = {True: "won"}


def _outcome(rank: str | None) -> str:
    if rank in config.WON_RANKS:
        return "受注"
    if rank in config.DEAD_RANKS:
        return "失注"
    return "進行中"


def _pain_points(activities: list[dict]) -> list[str]:
    """Distinct customer challenges (newest first), backed by daily-report lines."""
    seen: set[str] = set()
    out: list[str] = []
    for a in activities:
        ch = (a.get("customer_challenge") or "").strip()
        if ch and ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


def _matched_products(product_category: str) -> list[dict]:
    """Catalog products whose classification overlaps the deal's product_category."""
    cat = (product_category or "").strip()
    if not cat:
        return []
    out, seen = [], set()
    for p in store.all_products():
        hay = " ".join(str(p.get(k, "")) for k in ("product_name", "major", "mid", "minor"))
        if (cat in hay or hay in cat) and p["product_code"] not in seen:
            seen.add(p["product_code"])
            out.append({"code": p["product_code"], "name": p["product_name"],
                        "price": p.get("standard_unit_price", 0),
                        "specs": p.get("specs", "")})
    return out[:6]


@dataclass
class DocumentContext:
    deal_id: str
    customer_id: str
    customer: str
    industry: str
    size: str
    rep: str
    deal_name: str
    product_category: str
    rank: str
    band: str
    score: int
    today: str
    pain_points: list[str] = field(default_factory=list)
    daily_reports: list[str] = field(default_factory=list)
    products: list[dict] = field(default_factory=list)
    financials: dict = field(default_factory=dict)
    comparables: list[dict] = field(default_factory=list)
    health_reasons: list[str] = field(default_factory=list)
    environment: dict | None = None

    def to_preview(self) -> dict:
        """Compact dict for the confirm=false preview (what the file will be built from)."""
        return {
            "deal_id": self.deal_id,
            "customer": self.customer,
            "product_category": self.product_category,
            "band": self.band,
            "pain_points": self.pain_points[:5],
            "investment": self.financials.get("investment"),
            "n_products": len(self.products),
            "n_comparables": len(self.comparables),
        }


def build_document_context(deal_id: str) -> DocumentContext | None:
    """Assemble a DocumentContext for one deal, or None if the deal is unknown."""
    d = store.get_deal(deal_id)
    if not d:
        return None
    acts = store.activities_for_deal(deal_id)
    res = score_deal(d, acts, today=config.today())
    customer = store.get_customer(d["customer_id"]) or {}

    financials = {
        "investment": d.get("total_order_amount", 0),
        "total_revenue": d.get("total_revenue", 0),
        "gross_profit": d.get("total_order_gross_profit", 0),
        "hw_revenue": d.get("hw_order_revenue", 0),
        "sw_revenue": d.get("sw_order_revenue", 0),
        "service_revenue": d.get("paid_order_revenue", 0),
    }
    quote = store.quote_for_deal(deal_id)
    if quote:
        financials["quote_amount"] = quote.get("quote_amount")

    comparables = []
    for c in find_similar_deals(customer_id=d["customer_id"],
                                industry=customer.get("industry", ""))[:3]:
        comparables.append({
            "deal_id": c["deal_id"],
            "customer": store.customer_name(c["customer_id"]),
            "amount": c.get("total_order_amount", 0),
            "outcome": _outcome(c.get("order_rank")),
            "product_category": c.get("product_category", ""),
        })

    return DocumentContext(
        deal_id=deal_id,
        customer_id=d["customer_id"],
        customer=store.customer_name(d["customer_id"]),
        industry=customer.get("industry", ""),
        size=customer.get("size", ""),
        rep=store.rep_name(store.deal_rep_id(d)),
        deal_name=d.get("deal_name", "") or "",
        product_category=d.get("product_category", "") or "",
        rank=d.get("order_rank", "") or "",
        band=res.band,
        score=res.score,
        today=config.today().isoformat(),
        pain_points=_pain_points(acts),
        daily_reports=[a.get("daily_report", "") for a in acts[:5] if a.get("daily_report")],
        products=_matched_products(d.get("product_category", "")),
        financials=financials,
        comparables=comparables,
        health_reasons=res.top_reasons(3),
        environment=store.get_environment(d["customer_id"]),
    )
