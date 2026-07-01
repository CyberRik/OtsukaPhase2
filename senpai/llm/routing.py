"""Reasoning router for the Assistant — decide FAST (no_think) vs REASONING (think).

Our latency test showed the reasoning distill's <think> phase is pure overhead for
retrieval/provenance answers but beneficial for numeric interpretation and
cross-signal synthesis. This module isolates that *decision* behind a small,
swappable interface so the Assistant execution loop never grows routing logic.

Design contract:
  * The Assistant ASKS a router; it never decides itself.
  * `RoutingDecision` is provider-agnostic — a deterministic rule set today, an
    Atlas router / small classifier / LLM judge tomorrow, with no change to the
    execution loop. Pick the implementation via `get_reasoning_router()`.
  * Routing governs the FINAL SYNTHESIS round only. Tool-selection rounds stay
    fast (validated correct without reasoning); this layer adds reasoning back
    exactly where quality needs it.

Product constraints honoured: Assistant-only, no new retrieval, no agents,
deterministic-first. The default impl is local and explainable (every decision
carries a human-readable `reason`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class RoutingRequest:
    """What the router gets to see. Kept minimal and generic so alternative
    routers (classifier/LLM/Atlas) need nothing Senpai-specific beyond this."""
    message: str                                  # the user's query for this turn
    role: str = "junior"                          # junior | manager | research
    tools_used: list[str] = field(default_factory=list)  # tool names invoked this turn
    rounds: int = 0                               # tool rounds executed so far


@dataclass
class RoutingDecision:
    think: bool        # True → REASONING mode (<think>), False → FAST mode (no_think)
    reason: str        # human-readable justification (observability / trust)
    confidence: float  # 0..1 — how sure the router is


@runtime_checkable
class ReasoningRouter(Protocol):
    def route(self, request: RoutingRequest) -> RoutingDecision: ...


# --- deterministic, local first implementation ------------------------------

# Tools whose RESULTS need careful interpretation/synthesis in the answer:
# numeric deal-health, cross-signal manager analytics, analogy over past deals.
HIGH_REASONING_TOOLS: frozenset[str] = frozenset({
    "score_deal_health",        # numeric risk interpretation (the "77/100" slip)
    "list_at_risk_deals",       # cross-deal synthesis
    "team_pipeline_overview",   # cross-signal aggregate
    "team_report_digest",       # cross-report synthesis
    "rep_coaching_focus",       # multi-signal judgement
    "find_similar_deals",       # reasoning by analogy
    "segment_intelligence",     # cross-segment sensemaking (failure modes, win rates)
})

# Tools that just surface grounded records — restating them needs no reasoning.
LOW_REASONING_TOOLS: frozenset[str] = frozenset({
    "search_knowledge", "retrieve_playbook", "search_notes", "query_spr",
    "get_product_info", "search_products", "lookup_customer_environment",
    "get_seasonal_context", "get_calendar",
})

# Query intents that benefit from reasoning even before/without a HIGH tool:
# causal, contradiction, trajectory/trend, comparison, health/risk, synthesis.
_HIGH_INTENT = re.compile(
    r"なぜ|理由|どうして|矛盾|食い違|齟齬|推移|傾向|trend|trajectory|過去.*(比|推移)"
    r"|比較|compare|differ|健全度|リスク|risk|総合|まとめて分析|複数.*(踏ま|考慮)"
    r"|across|synthe|contradict|inconsist|why\b",
    re.IGNORECASE,
)


class DeterministicReasoningRouter:
    """Rule-based router: explainable, fast, no model call. Order matters — the
    strongest, most specific signals win, and each returns a clear `reason`."""

    def route(self, request: RoutingRequest) -> RoutingDecision:
        used = [t for t in request.tools_used if t]
        distinct = set(used)

        high_hit = distinct & HIGH_REASONING_TOOLS
        if high_hit:
            return RoutingDecision(
                think=True, confidence=0.9,
                reason=f"numeric/cross-signal tool used: {', '.join(sorted(high_hit))}")

        # Multi-tool synthesis needs reasoning only when at least one tool is NOT a
        # plain retrieval/provenance lookup. Several retrieval tools together
        # (query_spr + search_notes + lookup_customer_environment) just restate
        # grounded records — that's the FAST regime, so don't pay the <think> tax to
        # summarize them (this was a major Assistant latency sink on research turns).
        if len(distinct) >= 2 and (distinct - LOW_REASONING_TOOLS):
            return RoutingDecision(
                think=True, confidence=0.75,
                reason=f"multi-tool synthesis across {len(distinct)} tools "
                       "(≥1 non-retrieval)")

        if request.message and _HIGH_INTENT.search(request.message):
            return RoutingDecision(
                think=True, confidence=0.6,
                reason="query intent suggests interpretation/synthesis")

        if distinct:  # one or more, all retrieval/provenance tools
            return RoutingDecision(
                think=False, confidence=0.85,
                reason="retrieval/provenance answer — restating grounded records")

        return RoutingDecision(
            think=False, confidence=0.5,
            reason="direct answer, no tools — fast path")


# --- factory ----------------------------------------------------------------

_ROUTERS: dict[str, ReasoningRouter] = {}


def get_reasoning_router(name: str | None = None) -> ReasoningRouter:
    """Return the configured router (cached). Swap implementations here later
    (e.g. "atlas", "classifier", "llm") without touching the Assistant loop."""
    from senpai import config
    name = (name or getattr(config, "REASONING_ROUTER", "deterministic") or "deterministic").lower()
    if name not in _ROUTERS:
        # Only the deterministic router exists today; unknown names fall back to
        # it so a mis-set env can never break the Assistant.
        _ROUTERS[name] = DeterministicReasoningRouter()
    return _ROUTERS[name]
