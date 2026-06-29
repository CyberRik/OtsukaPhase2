"""The research capabilities: thin wrappers over the existing deterministic
store/scoring/retrieval/web logic. Each owns one domain, returns structured
Evidence, and never reasons.

Dependency shape (the part that proves the engine's DAG handling):

    crm ─┐
         ├─► health        (scores every deal id CRM + SimilarDeals surfaced)
similar ─┘
activities   (independent)
environment  (independent)

CRM and SimilarDeals emit deal *facts*; Health scores them; the gather step
re-merges facts + health into the legacy deal-summary shape. Web is used only on
the not-found fallback.
"""
from __future__ import annotations

from typing import Any, Mapping

from senpai.data import store
from senpai.orchestration import ExecContext
from senpai.orchestration.evidence import Evidence
from senpai.research import shaping
from senpai.retrieval.playbook import find_similar_deals
from senpai.tools.web import web_search_typed


class CRMCapability:
    """Customer + deals from the CRM/SPR store. Emits deal facts (no health) plus
    the catalog products implied by those deals and the public customer record."""
    name = "crm"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        mode = inputs["mode"]
        if mode == "deal":
            deal = store.get_deal(inputs["deal_id"])
            raw_deals = [deal] if deal else []
            active_deal_id = inputs["deal_id"]
            customer_id = deal["customer_id"] if deal else inputs.get("customer_id")
        else:  # customer
            customer_id = inputs["customer_id"]
            raw_deals = store.deals_for_customer(customer_id)
            active_deal_id = None

        facts = [shaping.deal_facts(d) for d in raw_deals]
        deal_ids = [d["deal_id"] for d in raw_deals]
        ctx.emit(f"{len(facts)} deal(s)")
        data = {
            "deals_facts": facts,
            "deal_ids": deal_ids,
            "active_deal_id": active_deal_id,
            "active_deal_facts": (shaping.deal_facts(raw_deals[0])
                                  if mode == "deal" and raw_deals else None),
            "products": shaping.products_for_deals(raw_deals),
            "customer": shaping.public_customer(store.get_customer(customer_id)),
        }
        return Evidence.ok(data, citations=[f"SPR {i}" for i in deal_ids],
                           status="ok" if facts else "empty",
                           provenance={"customer_id": customer_id})


class ActivitiesCapability:
    """Daily-report activities, scoped to the customer (or one deal), capped at 20
    exactly like the legacy bundle. Reports the raw count so provenance can record
    truncation."""
    name = "activities"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        if inputs["mode"] == "deal":
            raw = store.activities_for_deal(inputs["deal_id"])
        else:
            raw = store.activities_for_customer(inputs["customer_id"])
        shaped = [shaping.activity_summary(a) for a in raw[:20]]
        ctx.emit(f"{len(shaped)} activity record(s)")
        return Evidence.ok(
            {"activities": shaped, "raw_count": len(raw)},
            citations=[f"{a['deal_id']}@{a['date']}" for a in shaped if a.get("date")],
            status="ok" if shaped else "empty",
        )


class SimilarDealsCapability:
    """Comparable deals (top 3) via the existing playbook retrieval. Emits facts
    only; Health scores them alongside the customer's own deals."""
    name = "similar_deals"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        hits = find_similar_deals(customer_id=inputs.get("customer_id", ""),
                                  industry=inputs.get("industry", ""))[:3]
        facts = [shaping.deal_facts(d) for d in hits]
        deal_ids = [d["deal_id"] for d in hits]
        ctx.emit(f"{len(facts)} comparable(s)")
        return Evidence.ok({"similar_facts": facts, "deal_ids": deal_ids},
                           citations=[f"SPR {i}" for i in deal_ids],
                           status="ok" if facts else "empty")


class HealthCapability:
    """Scores every deal id surfaced upstream (CRM + SimilarDeals). Depends on both
    — the dependency edge the engine resolves before running this. Pure
    `score_deal`; no new scoring logic."""
    name = "health"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        ids: list[str] = []
        for dep in ctx.deps.values():
            ids.extend(dep.data.get("deal_ids", []))
        seen: set[str] = set()
        health_by_deal: dict[str, dict] = {}
        for deal_id in ids:
            if deal_id in seen:
                continue
            seen.add(deal_id)
            d = store.get_deal(deal_id)
            if d:
                health_by_deal[deal_id] = shaping.health_read(d, inputs["today"])
        ctx.emit(f"scored {len(health_by_deal)} deal(s)")
        return Evidence.ok({"health_by_deal": health_by_deal},
                           status="ok" if health_by_deal else "empty")


class EnvironmentCapability:
    """The customer's IT environment record (or absent)."""
    name = "environment"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        env = store.get_environment(inputs["customer_id"])
        ctx.emit("environment found" if env else "no environment record")
        if not env:
            return Evidence.empty(provenance={"customer_id": inputs["customer_id"]})
        return Evidence.ok({"environment": env},
                           citations=[f"env:{inputs['customer_id']}"])


class WebCapability:
    """External web search (Tavily) — the not-found fallback. Identical call to the
    legacy `web_search_typed`, so the `web`/`source` events are unchanged."""
    name = "web"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        result = web_search_typed(inputs["query"])
        ctx.emit(f"web {result.get('status')}")
        return Evidence.ok(
            {"web": result},
            citations=[r.get("url", "") for r in (result.get("results") or [])],
            status="ok" if result.get("status") == "found" else "partial",
        )


def build_registry():
    """A registry with all six research capabilities, ready for the engine."""
    from senpai.orchestration import CapabilityRegistry
    reg = CapabilityRegistry()
    for cap in (CRMCapability(), ActivitiesCapability(), SimilarDealsCapability(),
                HealthCapability(), EnvironmentCapability(), WebCapability()):
        reg.register(cap)
    return reg
