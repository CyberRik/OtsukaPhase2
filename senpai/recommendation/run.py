"""Entry point for the recommendation engine."""
from __future__ import annotations

from typing import Iterator

from senpai.orchestration.evidence import EvidenceBundle
from senpai.recommendation.context import build_context
from senpai.recommendation.ranking import rank_candidates
from senpai.recommendation.solutions import generate_solution_candidates
from senpai.recommendation.explanation import explain_candidates
from senpai.recommendation.schema import Recommendation


def run_solution_advisor(customer_id: str, deal_id: str = "") -> list[Recommendation]:
    """Top-level synchronous entry point for the Solution Advisor.

    Given a customer context, it retrieves deterministic candidates, ranks them,
    and runs a single LLM explanation pass to produce structured Recommendations.
    """
    # 1. Build the deterministic context from real account state
    ctx = build_context(customer_id, deal_id)
    if not ctx:
        return []

    # 2. Generate and rank deterministic candidates (zero LLM involved)
    raw_candidates = generate_solution_candidates(ctx, limit=10)
    top_candidates = rank_candidates(raw_candidates, limit=5)
    
    if not top_candidates:
        return []

    # 3. Create a pseudo EvidenceBundle that the reasoner can use.
    # In a full orchestration pipeline, this would come from a Parallel planner.
    # Here, we package the context as evidence for the explanation layer.
    from senpai.orchestration.evidence import Evidence
    
    fragments = {}
    
    # Pack opportunities (expansion signals) as evidence
    for opp in ctx.opportunities:
        evidence = Evidence.ok({
            "type": "expansion_signal",
            "signal": opp.to_dict()
        }, citations=[f"expansion:{opp.kind}:{opp.target}"])
        fragments[f"opp_{opp.kind}_{opp.target}"] = evidence

    # Pack category/industry as evidence
    if ctx.category:
        evidence = Evidence.ok({
            "type": "account_profile",
            "category": ctx.category,
            "industry": ctx.industry,
        }, citations=["category_match"])
        fragments["account_profile"] = evidence
        
    bundle = EvidenceBundle(run_id="solution_advisor", fragments=fragments)

    # 4. LLM explains and prioritizes the deterministic candidates
    recommendations = explain_candidates(bundle, top_candidates)
    
    # Sort by match_score and confidence
    recommendations.sort(key=lambda r: (r.match_score, r.confidence), reverse=True)
    return recommendations
