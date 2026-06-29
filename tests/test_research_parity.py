"""M1 golden regression: the orchestration-engine research gather must reproduce
the legacy inline gather byte-for-byte.

The legacy builders (`_build_research_bundle` / `_build_deal_context_bundle`) are
the oracle; the engine-backed builders (`*_orch`) are the new path the live
`/research` endpoint calls. Parity here is what licenses keeping the new path and
(later) deleting the legacy one.

Strategy: the LLM answer is non-deterministic, so we do NOT compare generated text.
Instead we prove the *evidence bundle fed to the reasoner is identical* — same
data, same citations source, same provenance — which makes artifact quality
identical by construction. We also assert the deterministic control-flow (ambiguous
/ not-found / web-fallback) and that the engine path degrades on partial failure
where the legacy path would crash.
"""
from __future__ import annotations

import pytest

from senpai import config
from senpai.data import store
from senpai.api import server as srv

TODAY = config.today()


def _customers_with_deals(limit=40):
    out = []
    for c in store.all_customers():
        if store.deals_for_customer(c["customer_id"]):
            out.append(c)
        if len(out) >= limit:
            break
    return out


def _resolved(customer: dict):
    """A resolution object the legacy builder accepts, pinned to one customer."""
    res = store.resolve_customer_detailed(customer["name"])
    if res.status == "resolved" and res.customer:
        return res
    return None


# ── scenario: valid customer (resolved, has internal records) ───────────────
@pytest.mark.parametrize("customer", _customers_with_deals(), ids=lambda c: c["customer_id"])
def test_valid_customer_bundle_parity(customer):
    res = _resolved(customer)
    if res is None:
        pytest.skip(f"{customer['customer_id']} does not resolve uniquely")
    msg = f"tell me about {customer['name']}"
    target = srv._research_target(msg)
    legacy = srv._build_research_bundle(msg, target, res)
    orch = srv._build_research_bundle_orch(msg, target, res)
    assert orch.to_dict() == legacy.to_dict()


# ── scenario: deal-in-focus context bundle ──────────────────────────────────
@pytest.mark.parametrize("deal", store.open_deals()[:40], ids=lambda d: d["deal_id"])
def test_deal_context_bundle_parity(deal):
    msg = f"research {deal['deal_id']}"
    target = srv._research_target(msg)
    legacy = srv._build_deal_context_bundle(msg, target, deal)
    orch = srv._build_deal_context_bundle_orch(msg, target, deal)
    assert orch.to_dict() == legacy.to_dict()


# ── scenario: citations preserved (same source ids surface) ─────────────────
def test_citations_present_and_grounded():
    customer = _customers_with_deals(1)[0]
    res = _resolved(customer)
    assert res is not None
    orch = srv._build_research_bundle_orch("tell me about", "x", res)
    d = orch.to_dict()
    # Every deal summary carries a health band/score/reasons (the citable grounding
    # the artifact quotes), exactly as the legacy bundle did.
    for deal in d["deals"]:
        assert set(deal["health"]) == {"band", "score", "reasons"}
        assert deal["deal_id"]


# ── scenario: customer not found (resolution-level, no gather) ──────────────
def test_not_found_returns_empty_shell():
    res = store.resolve_customer_detailed("zzz-nonexistent-company-xyz")
    assert res.status == "not_found"
    legacy = srv._build_research_bundle("tell me about zzz", "zzz", res)
    orch = srv._build_research_bundle_orch("tell me about zzz", "zzz", res)
    assert orch.to_dict() == legacy.to_dict()
    assert orch.customer is None and orch.deals == []


# ── scenario: web fallback ──────────────────────────────────────────────────
def test_web_fallback_matches_direct_call(monkeypatch):
    # The live Tavily answer is non-deterministic, so we pin the underlying call to
    # a sentinel and assert the WebCapability passes it through UNCHANGED — i.e. the
    # engine path is a faithful wrapper of the legacy `web_search_typed`.
    import senpai.research.capabilities as caps
    from senpai.research import web_search_via_engine
    sentinel = {"status": "found", "query": "q", "answer": "A", "live": True,
                "reason": "", "results": [{"title": "t", "url": "u", "content": "c",
                                           "score": 0.9}]}
    monkeypatch.setattr(caps, "web_search_typed", lambda q: sentinel)
    assert web_search_via_engine("anything") == sentinel


# ── scenario: partial retrieval failure (engine degrades, never crashes) ────
def test_partial_failure_degrades(monkeypatch):
    customer = _customers_with_deals(1)[0]
    res = _resolved(customer)
    assert res is not None

    # Make the Environment capability blow up mid-run.
    import senpai.research.capabilities as caps

    def boom(_cid):
        raise RuntimeError("simulated store outage")

    monkeypatch.setattr(caps.store, "get_environment", boom)

    # Legacy path would raise; the engine path must degrade to environment=None and
    # still return a complete bundle for the other sources.
    orch = srv._build_research_bundle_orch("tell me about", "x", res)
    d = orch.to_dict()
    assert d["environment"] is None
    assert d["deals"]  # the rest of the gather still succeeded
    # provenance still reports environment, as not_found
    env_prov = [p for p in d["provenance"] if p.get("source") == "environment"]
    assert env_prov and env_prov[0]["status"] == "not_found"
