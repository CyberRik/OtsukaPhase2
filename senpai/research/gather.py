"""Run the research plan on the engine and assemble the result into the exact
field set the legacy `_build_research_bundle` / `_build_deal_context_bundle`
produced. The route wraps the returned dict in its `ResearchBundle`.

The assembly re-merges CRM/SimilarDeals facts with Health scores into the legacy
deal-summary shape and rebuilds provenance identically (per mode). Capability
failures degrade gracefully: a missing fragment is treated as empty, exactly as if
that source had returned nothing — the run never crashes.
"""
from __future__ import annotations

from typing import Callable

from senpai.orchestration import ExecutionEngine, EvidenceBundle
from senpai.research.capabilities import build_registry
from senpai.research.plan import research_plan, web_plan

Emit = Callable[[dict], None]
_NOOP: Emit = lambda _ev: None


def _run(plan, registry, emit: Emit | None) -> EvidenceBundle:
    return ExecutionEngine(registry or build_registry()).run(plan, emit or _NOOP)


def _data(bundle: EvidenceBundle, task_id: str) -> dict:
    """A task's evidence data, or {} if it failed/absent (graceful degradation)."""
    ev = bundle.get(task_id)
    if ev is None or ev.status == "error":
        return {}
    return dict(ev.data)


def research_bundle_fields(*, mode: str, query: str, target: str,
                           resolution: dict, customer: dict | None,
                           customer_id: str, deal_id: str | None,
                           industry: str, today, registry=None,
                           emit: Emit | None = None) -> dict:
    """Engine-gathered equivalent of the legacy bundle, as a field dict."""
    plan = research_plan(mode, customer_id=customer_id, deal_id=deal_id,
                         industry=industry, today=today)
    bundle = _run(plan, registry, emit)

    crm = _data(bundle, "crm")
    acts = _data(bundle, "activities")
    sim = _data(bundle, "similar")
    health = _data(bundle, "health").get("health_by_deal", {})
    environment = _data(bundle, "environment").get("environment")

    def merge(facts: dict) -> dict:
        # Re-attach the health block scored by the Health capability -> the legacy
        # `_deal_summary` shape. Missing score (degraded) -> empty health, never KeyError.
        h = health.get(facts["deal_id"], {"band": None, "score": None, "reasons": []})
        return {**facts, "health": h}

    deals = [merge(f) for f in crm.get("deals_facts", [])]
    similar_deals = [merge(f) for f in sim.get("similar_facts", [])]
    active_deal_facts = crm.get("active_deal_facts")
    active_deal = merge(active_deal_facts) if active_deal_facts else None
    activities = acts.get("activities", [])
    raw_count = acts.get("raw_count", len(activities))

    fields = {
        "query": query,
        "target": target,
        "resolution": resolution,
        "customer": customer,
        "active_deal_id": crm.get("active_deal_id"),
        "active_deal": active_deal,
        "deals": deals,
        "activities": activities,
        "environment": environment,
        "products": crm.get("products", []),
        "similar_deals": similar_deals,
        "provenance": _provenance(mode, deal_id, deals, activities, raw_count, environment),
    }
    return fields


def _provenance(mode: str, deal_id: str | None, deals: list, activities: list,
                raw_count: int, environment) -> list[dict]:
    """Byte-for-byte the provenance the legacy builders appended (per mode)."""
    prov: list[dict] = []
    if mode == "deal":
        prov.append({"source": "active_deal_context", "priority": 1, "deal_id": deal_id})
    prov.append({"source": "internal_records", "priority": 1, "status": "found"})
    prov.append({"source": "deals", "priority": 2,
                 "count": 1 if mode == "deal" else len(deals)})
    prov.append({"source": "activities", "priority": 3, "count": len(activities),
                 "truncated": raw_count > len(activities)})
    prov.append({"source": "environment", "priority": 4,
                 "status": "found" if environment else "not_found"})
    return prov


def web_search_via_engine(query: str, registry=None, emit: Emit | None = None) -> dict:
    """The not-found web fallback, run through the WebCapability. Returns the same
    dict the legacy `web_search_typed(query)` returned."""
    bundle = _run(web_plan(query), registry, emit)
    return _data(bundle, "web").get("web",
                                    {"status": "error", "query": query, "answer": "",
                                     "results": [], "live": False, "reason": "request_failed"})
