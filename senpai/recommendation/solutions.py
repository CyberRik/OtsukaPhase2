"""Solution candidates — the first concrete domain on the recommendation engine.

Two query layers, each grounded in real account state (not a "goal" string):

  1. category/industry  — what this account is broadly buying (the e-commerce-
     grade signal: category -> similar category). Necessary, not sufficient.
  2. expansion signals   — senpai.account.expansion's deterministic rule engine
     (cross-sell/upsell/growth), already correctly owned/gap-aware: cross-sell
     only ever targets a category the account does NOT own; upsell only ever
     targets one it DOES own and shows a concrete refresh trigger. Reusing it
     here (rather than re-deriving owned/gap logic) is what makes this
     "consultant, not category search" — a candidate exists because something
     is actually missing or aging at this account, not just same-category noise.

Each signal's query result is boosted by a confidence MULTIPLIER (not a flat
add), since solution_knowledge's relevance score is a small RRF value (~0.03-
0.06) — an additive boost would drown out real retrieval-relevance differences
between hits; a multiplier preserves them while still promoting signal-backed
candidates over a bare category match.

Deliberately NOT attempted here: excluding a candidate because the account
already owns that exact product (SKU-level). Product pages are marketing prose
("医療情報の電子化対応のメリット"), not catalog names — fuzzy-matching those against
`store.get_product()` names is unreliable enough that a wrong exclusion (hiding
a genuinely good recommendation) seems worse than an occasional redundant one.
Category-level owned-awareness (via expansion_opportunities) is the reliable
signal; SKU-level dedup is a real V2, not a shortcut worth faking now.
"""
from __future__ import annotations

from senpai.recommendation.candidate import Candidate
from senpai.recommendation.context import RecommendationContext
from senpai.recommendation.ranking import rank_candidates
from senpai.retrieval.solution_knowledge import search_solution_knowledge

_CONFIDENCE_BOOST = {"high": 1.6, "medium": 1.3, "low": 1.1}


def _queries(ctx: RecommendationContext) -> list[tuple[str, str, float]]:
    """(query, reason, boost_multiplier) tuples — one per query layer."""
    out: list[tuple[str, str, float]] = []
    base = " ".join(p for p in (ctx.category, ctx.industry) if p)
    if base:
        out.append((base, "category_match", 1.0))
    for opp in ctx.opportunities:
        query = " ".join(p for p in (opp.target, opp.rationale) if p)
        reason = f"expansion:{opp.kind}:{opp.target}"
        out.append((query, reason, _CONFIDENCE_BOOST.get(opp.confidence, 1.0)))
    return out


def generate_solution_candidates(ctx: RecommendationContext, *, limit: int = 5,
                                 per_query_limit: int = 5) -> list[Candidate]:
    """Deterministic, no LLM. Every returned Candidate.id is a real Otsuka
    product-page URL that survived solution_knowledge's own lexical floor
    (see senpai/retrieval/semantic.py's lexical_support_urls) — this function
    adds ranking signal on top, it never invents or loosens what counts as a
    real match."""
    queries = _queries(ctx)
    if not queries:
        return []

    candidates: list[Candidate] = []
    for query, reason, boost in queries:
        for hit in search_solution_knowledge(query, limit=per_query_limit):
            sol = hit["solution"]
            url = sol["source"]
            if not url:
                continue
            candidates.append(Candidate(
                kind="solution",
                id=url,
                title=sol["name"],
                match_score=float(sol["relevance"]) * boost,
                reasons=(reason,),
                evidence=(url,),
                payload={"category": sol["category"], "summary": sol["summary"], "source": url},
            ))

    return rank_candidates(candidates, limit=limit)
