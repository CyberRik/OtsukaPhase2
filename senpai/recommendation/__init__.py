"""Recommendation engine — deterministic candidate generation + ranking, with an
LLM confined to explaining/prioritizing what this layer already found.

Non-negotiable pipeline, enforced by module boundaries, not just convention:

    (grounded context) -> candidate generation -> candidate ranking -> [LLM explains]

The LLM is never given a blank page to "recommend from" — every candidate this
layer emits already has a real, checkable id (a URL, a record id, ...) and a
deterministic `match_score`. Phase 2's explanation layer narrates a closed list;
it cannot introduce an item that didn't come from here. This is what makes "no
hallucinated recommendations" an architectural fact rather than a prompt request.

Kept domain-agnostic on purpose: `candidate.py`/`ranking.py`/`context.py` know
nothing about products. `solutions.py` is the first concrete domain (candidates
= real Otsuka product/solution pages, via senpai.retrieval.solution_knowledge).
Ranking products, actions, playbooks, documents, or experts later means adding a
new `<domain>.py` generator that returns `Candidate` objects — `ranking.py`
doesn't change.

Phase 1 (this): candidate generation + ranking, fully testable with no LLM and
no orchestration engine — plain functions over the store + retrieval layer.
Phase 2 adds the Recommendation schema + one JSON-schema-constrained LLM pass.
Phase 3 wires this into a tool, the planner, and the chat UI.
"""
from __future__ import annotations

from .candidate import Candidate
from .context import RecommendationContext, build_context
from .ranking import rank_candidates
from .schema import Recommendation
from .explanation import explain_candidates
from .solutions import generate_solution_candidates

__all__ = [
    "Candidate",
    "RecommendationContext",
    "build_context",
    "rank_candidates",
    "Recommendation",
    "explain_candidates",
    "generate_solution_candidates",
]
