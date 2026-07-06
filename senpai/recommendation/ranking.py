"""Candidate ranking — purely mechanical, domain-agnostic: dedupe, sort, truncate.

Deliberately NOT where domain scoring logic lives. A domain's generator (e.g.
solutions.py) is responsible for computing a `match_score` that already reflects
whatever that domain cares about (retrieval relevance, a signal boost, ...); this
module just merges duplicate proposals for the same `id` (keeping the
highest-scoring one, and unioning why it was proposed) and orders the result.
Any future domain's Candidate list works here unchanged.
"""
from __future__ import annotations

from senpai.recommendation.candidate import Candidate


def rank_candidates(candidates: list[Candidate], *, limit: int = 5) -> list[Candidate]:
    """Dedupe by `id` (multiple generation queries can rediscover the same item —
    keep the highest match_score, union the reasons/evidence so a candidate found
    via two signals shows both), sort by match_score descending, truncate."""
    best: dict[str, Candidate] = {}
    for c in candidates:
        prev = best.get(c.id)
        if prev is None:
            best[c.id] = c
            continue
        if c.match_score > prev.match_score:
            best[c.id] = _merge(c, prev)
        else:
            best[c.id] = _merge(prev, c)
    ranked = sorted(best.values(), key=lambda c: c.match_score, reverse=True)
    return ranked[:limit]


def _merge(winner: Candidate, other: Candidate) -> Candidate:
    """`winner` keeps its score/title/payload; reasons/evidence from both are
    unioned (order-preserving) so a candidate surfaced by two independent signals
    carries both explanations forward instead of silently dropping one."""
    reasons = winner.reasons + tuple(r for r in other.reasons if r not in winner.reasons)
    evidence = winner.evidence + tuple(e for e in other.evidence if e not in winner.evidence)
    return Candidate(kind=winner.kind, id=winner.id, title=winner.title,
                     match_score=winner.match_score, reasons=reasons,
                     evidence=evidence, payload=winner.payload)
