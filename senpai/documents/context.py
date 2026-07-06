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


def _comparable_deals(deal_id: str, product_category: str, customer_id: str,
                      industry: str, target_amount: int) -> list[dict]:
    """Reference cases for a proposal. A rep cites deals a prospect can relate to,
    so we prefer **the same product category at OTHER customers**, one deal per
    customer (diverse — never three from one firm), won outcomes first, then closest
    in size. Falls back to industry-similar deals only when the category is too thin
    to fill three, so a proposal always shows *something* real rather than nothing."""
    cat = (product_category or "").strip()
    picked: list[dict] = []
    seen_customers: set[str] = {customer_id}
    if cat:
        cands = [d for d in store.all_deals()
                 if d.get("product_category") == cat and d["customer_id"] not in seen_customers]

        def _key(d: dict):
            cust = store.get_customer(d["customer_id"]) or {}
            won = d.get("order_rank") in config.WON_RANKS
            same_ind = bool(industry) and cust.get("industry") == industry
            amt_gap = abs(d.get("total_order_amount", 0) - (target_amount or 0))
            return (won, same_ind, -amt_gap)

        for d in sorted(cands, key=_key, reverse=True):
            if d["customer_id"] in seen_customers:
                continue                       # one per customer → diverse social proof
            seen_customers.add(d["customer_id"])
            picked.append(d)
            if len(picked) >= 3:
                break
    if len(picked) < 3:                        # top up with industry-similar deals
        for d in find_similar_deals(customer_id=customer_id, industry=industry, limit=6):
            if d["deal_id"] == deal_id or d["customer_id"] in seen_customers:
                continue
            seen_customers.add(d["customer_id"])
            picked.append(d)
            if len(picked) >= 3:
                break
    return picked


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
    # Every deal this context is grounded in — just [self] for the normal
    # single-deal proposal; >1 entry when the rep asked for a customer's deals to
    # be covered together (see `deal_ids` on build_document_context). The deck
    # gets an extra "対象案件一覧" slide whenever this has more than one entry.
    deals: list[dict] = field(default_factory=list)

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
            "n_deals": len(self.deals),
        }


def build_document_context(deal_id: str, *, deal_ids: list[str] | None = None) -> DocumentContext | None:
    """Assemble a DocumentContext for one deal, or None if the deal is unknown.

    `deal_ids`, when given (a customer's full deal list, for an "all deals"
    proposal request), additionally merges those deals' pain points, matched
    products, and comparables into the same deck, and sums their financials.
    `deal_id` stays the PRIMARY deal — its health/rank/band still drives the
    health read, and its quote/discount (if any) still drives the ROI framing,
    since a blended discount rate across several deals would misstate any one
    of their actual prices."""
    d = store.get_deal(deal_id)
    if not d:
        return None
    others = [o for did in (deal_ids or []) if did != deal_id and (o := store.get_deal(did))]
    all_deals = [d, *others]
    customer = store.get_customer(d["customer_id"]) or {}

    acts = store.activities_for_deal(deal_id)
    for o in others:
        acts = acts + store.activities_for_deal(o["deal_id"])
    res = score_deal(d, store.activities_for_deal(deal_id), today=config.today())

    financials = {
        "investment": sum(x.get("total_order_amount", 0) for x in all_deals),
        "total_revenue": sum(x.get("total_revenue", 0) for x in all_deals),
        "gross_profit": sum(x.get("total_order_gross_profit", 0) for x in all_deals),
        "hw_revenue": sum(x.get("hw_order_revenue", 0) for x in all_deals),
        "sw_revenue": sum(x.get("sw_order_revenue", 0) for x in all_deals),
        "service_revenue": sum(x.get("paid_order_revenue", 0) for x in all_deals),
    }
    if not others:  # a blended discount rate across deals would misstate any one price
        quote = store.quote_for_deal(deal_id)
        if quote:
            financials["quote_amount"] = quote.get("quote_amount")
            financials["standard_amount"] = quote.get("standard_amount")
            financials["discount_rate"] = quote.get("discount_rate")
            financials["discount_amount"] = quote.get("discount_amount")

    seen_codes: set[str] = set()
    products: list[dict] = []
    for cat in dict.fromkeys(x.get("product_category", "") or "" for x in all_deals):
        if not cat:
            continue
        for p in _matched_products(cat):
            if p["code"] not in seen_codes:
                seen_codes.add(p["code"])
                products.append(p)

    seen_customers = {d["customer_id"]}
    comparables: list[dict] = []
    for x in all_deals:
        for c in _comparable_deals(x["deal_id"], x.get("product_category", "") or "",
                                   x["customer_id"], customer.get("industry", ""),
                                   x.get("total_order_amount", 0)):
            if c["customer_id"] in seen_customers:
                continue
            seen_customers.add(c["customer_id"])
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
        products=products[:6 if others else 4],
        financials=financials,
        comparables=comparables[:3 + min(2, len(others))],
        health_reasons=res.top_reasons(3),
        environment=store.get_environment(d["customer_id"]),
        deals=[{"deal_id": x["deal_id"], "deal_name": x.get("deal_name", ""),
               "product_category": x.get("product_category", ""),
               "amount": x.get("total_order_amount", 0), "rank": x.get("order_rank", "")}
              for x in all_deals],
    )
