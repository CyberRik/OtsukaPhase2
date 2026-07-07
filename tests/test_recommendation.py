"""Recommendation engine — Phase 1 (candidate generation + ranking). No LLM
anywhere in this file; every assertion is about deterministic behavior, per the
architecture's non-negotiable rule that candidates are never LLM-generated.
"""
from __future__ import annotations

from senpai.recommendation.candidate import Candidate
from senpai.recommendation.context import RecommendationContext, build_context
from senpai.recommendation.ranking import rank_candidates
from senpai.recommendation.solutions import generate_solution_candidates

# A real customer/deal with genuine cross-sell signals (found via the actual
# store + account.expansion — not fabricated), so candidate generation is
# exercised against real account state, not a synthetic fixture.
_CUSTOMER = "C13"
_DEAL = "D001"


# --- ranking: pure, synthetic, no store/network involved -------------------

def test_rank_candidates_dedupes_keeps_higher_score_and_merges_reasons():
    low = Candidate(kind="solution", id="u1", title="A", match_score=0.1,
                    reasons=("category_match",), evidence=("u1",))
    high = Candidate(kind="solution", id="u1", title="A", match_score=0.3,
                     reasons=("expansion:cross_sell:x",), evidence=("u1",))
    ranked = rank_candidates([low, high], limit=5)
    assert len(ranked) == 1
    assert ranked[0].match_score == 0.3
    assert set(ranked[0].reasons) == {"category_match", "expansion:cross_sell:x"}


def test_rank_candidates_sorts_descending_and_truncates():
    cands = [Candidate(kind="solution", id=f"u{i}", title=f"T{i}", match_score=s)
             for i, s in enumerate([0.05, 0.9, 0.3, 0.6, 0.1, 0.2])]
    ranked = rank_candidates(cands, limit=3)
    assert [c.match_score for c in ranked] == [0.9, 0.6, 0.3]


def test_rank_candidates_empty_input():
    assert rank_candidates([], limit=5) == []


# --- context: deterministic resolution from the store -----------------------

def test_build_context_resolves_real_customer():
    ctx = build_context(_CUSTOMER, _DEAL)
    assert ctx is not None
    assert ctx.customer_id == _CUSTOMER
    assert ctx.deal_id == _DEAL
    assert ctx.industry
    assert ctx.category
    assert isinstance(ctx.opportunities, tuple)
    assert isinstance(ctx.owned_categories, tuple)


def test_build_context_unknown_customer_returns_none():
    assert build_context("NOT-A-REAL-CUSTOMER-ID") is None


def test_build_context_falls_back_to_largest_open_deal_when_none_named():
    ctx = build_context(_CUSTOMER)
    assert ctx is not None
    assert ctx.deal_id  # resolved deterministically, not left blank


# --- solution candidate generation ------------------------------------------

def test_generate_solution_candidates_uses_real_expansion_signals():
    ctx = build_context(_CUSTOMER, _DEAL)
    assert ctx.opportunities, "fixture customer must have real expansion signals"
    candidates = generate_solution_candidates(ctx, limit=5)
    assert candidates
    for c in candidates:
        assert c.kind == "solution"
        assert c.id.startswith("http"), "candidate id must be a real, checkable URL"
        assert c.reasons
        assert c.evidence == (c.id,)
    # At least one candidate must trace back to an expansion signal, not just
    # the bare category/industry query — this is the "consultant, not
    # e-commerce" property: real account state drove at least one hit.
    assert any(r.startswith("expansion:") for c in candidates for r in c.reasons)


def test_generate_solution_candidates_category_only_still_works():
    """No expansion signals at all — the base category/industry layer alone
    must still produce candidates (graceful degrade, not an empty result)."""
    ctx = RecommendationContext(customer_id="X", category="ソフトウェア", industry="士業")
    candidates = generate_solution_candidates(ctx, limit=5)
    assert candidates
    assert all(c.reasons == ("category_match",) for c in candidates)


def test_generate_solution_candidates_empty_context_returns_empty_not_error():
    ctx = RecommendationContext(customer_id="X")
    assert generate_solution_candidates(ctx, limit=5) == []


def test_generate_solution_candidates_is_deterministic():
    ctx = build_context(_CUSTOMER, _DEAL)
    first = [c.id for c in generate_solution_candidates(ctx, limit=5)]
    second = [c.id for c in generate_solution_candidates(ctx, limit=5)]
    assert first == second


def test_generate_solution_candidates_respects_limit():
    ctx = build_context(_CUSTOMER, _DEAL)
    assert len(generate_solution_candidates(ctx, limit=2)) <= 2
