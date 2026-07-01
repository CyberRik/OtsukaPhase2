"""Unit tests for Segment Intelligence (GraphRAG community summarization).

No GPU, no model — the deterministic partition/stats and the runtime fallback
build are pure Python. Pins SENPAI_TODAY so seed-derived counts are stable. Like
test_manager_tools, expectations are derived from the same store/engine the code
uses, so we assert *aggregation + grounding invariants* rather than hardcoding
magic numbers that would drift with the seed.
"""
from __future__ import annotations

import os

os.environ.setdefault("SENPAI_TODAY", "2026-06-16")  # before any config.today() call

from senpai.data import store
from senpai.graph import communities
from senpai.tools import impl


def _outcome(rank):
    if rank in ("1_Confirmed",):
        return "won"
    if rank in ("7_Lost", "8_Cancelled"):
        return "lost"
    return "open"


def test_partition_accounts_for_every_deal():
    """Category rollups partition the deal set exactly — each deal lands in exactly
    one category, and the rollups' deal counts sum to the full seed."""
    reports = communities.build_reports()
    cats = [r for r in reports if r["level"] == "category"]
    total = sum(r["n_deals"] for r in cats)
    assert total == len(store.all_deals())
    # Category rollup ids are unique.
    assert len({r["id"] for r in cats}) == len(cats)


def test_leaf_threshold_and_rollup():
    """Every emitted leaf clears the closed-deal threshold; each leaf's parent
    category is always present as a rollup (the home for thin leaves)."""
    from senpai import config
    reports = communities.build_reports()
    leaves = [r for r in reports if r["level"] == "leaf"]
    cats = {r["category"] for r in reports if r["level"] == "category"}
    for lf in leaves:
        assert (lf["n_won"] + lf["n_lost"]) >= config.SEGMENT_MIN_DEALS
        assert lf["category"] in cats


def test_stats_match_hand_count_for_a_category():
    """Deterministic win rate / counts for one category match a straight recount off
    the store — proves the numbers are real aggregates, not invented."""
    reports = communities.build_reports()
    cat_report = next(r for r in reports if r["level"] == "category")
    cat = cat_report["category"]
    deals = [d for d in store.all_deals()
             if ((d.get("product_category") or "").strip() or "未分類") == cat]
    won = sum(1 for d in deals if _outcome(d.get("order_rank")) == "won")
    lost = sum(1 for d in deals if _outcome(d.get("order_rank")) == "lost")
    assert cat_report["n_deals"] == len(deals)
    assert cat_report["n_won"] == won
    assert cat_report["n_lost"] == lost
    if won + lost:
        assert cat_report["win_rate"] == round(won / (won + lost), 3)


def test_narratives_never_invent_numbers():
    """The grounding invariant: no numeric token in any narrative is absent from that
    segment's stats (this is exactly the gate build_communities applies to the LLM)."""
    for r in communities.build_reports():
        assert communities.ungrounded_numbers(r["narrative_ja"], r) == [], r["id"]


def test_ungrounded_numbers_flags_a_fake_figure():
    """Sanity-check the gate itself: an invented percentage is caught."""
    r = communities.build_reports()[0]
    assert "999" in communities.ungrounded_numbers("勝率999%と急上昇。", r)


def test_tool_dispatch_returns_grounded_string_and_never_raises():
    out = impl.dispatch("segment_intelligence",
                        {"query": "製造業のサーバー案件はなぜ負ける？", "outcome": "lost"})
    assert isinstance(out, str) and out.strip()
    assert "[error]" not in out
    # Broad, un-anchored question still returns something (category rollups).
    broad = impl.dispatch("segment_intelligence", {"query": "どのカテゴリの勝率が低い？"})
    assert broad.strip() and "[error]" not in broad


def test_format_report_cites_evidence_deals():
    reports = communities.build_reports()
    r = next(r for r in reports if r["deal_ids"])
    rendered = communities.format_report(r)
    assert "根拠案件" in rendered
    assert r["deal_ids"][0] in rendered
