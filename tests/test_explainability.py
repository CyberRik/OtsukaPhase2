"""Tests for the Coaching Explainability layer.

Verifies that explanations are grounded in real data, that outcome statistics
are computed correctly, and that the integration with review_note / coaching
workspace produces well-formed explanations.
"""
from __future__ import annotations

import os
from datetime import date

# Pin the date so tests are deterministic against the seed data.
os.environ.setdefault("SENPAI_TODAY", "2026-06-16")

from senpai import config
from senpai.coach.explainability import (
    Explanation,
    OutcomeStats,
    build_review_explanations,
    compute_outcome_stats,
    explain_coaching_issue,
    explain_lens,
    explain_signal,
    explain_presence,
)
from senpai.coach.review import LENSES, CoachReview, review_note
from senpai.coaching import coaching_workspace
from senpai.data import store
from senpai.health.scoring import Signal, score_deal


TODAY = config.today()


# ---------------------------------------------------------------------------
# Unit tests — explainability engine
# ---------------------------------------------------------------------------

class TestComputeOutcomeStats:
    """Outcome stats from real closed deals."""

    def test_returns_none_below_min_sample(self):
        """Conditions that match < 5 deals → None (no misleading stats)."""
        stats = compute_outcome_stats(
            lambda d, acts: False,  # matches nothing
            "テスト条件",
            "test condition",
        )
        assert stats is None

    def test_returns_stats_above_min_sample(self):
        """With a broad enough condition, we get actual stats."""
        stats = compute_outcome_stats(
            lambda d, acts: True,  # matches everything
            "全案件",
            "all deals",
        )
        assert stats is not None
        assert isinstance(stats, OutcomeStats)
        assert stats.total_similar == stats.won + stats.lost
        assert stats.total_similar >= 5
        assert 0 <= stats.loss_rate <= 1

    def test_missing_dm_stats(self):
        """Deals without DM should be a large enough pool to report stats."""
        from senpai.coach.cases import _has_decision_maker
        stats = compute_outcome_stats(
            lambda d, acts: not _has_decision_maker(acts),
            "決裁者が未特定の案件",
            "Deals without DM",
        )
        # With 540+ deals in seed data, there should be enough matches
        if stats is not None:
            assert stats.total_similar >= 5
            assert stats.loss_rate >= 0


class TestExplainLens:
    """Lens explanations trace back to real triggers and evidence."""

    def test_decision_maker_lens(self):
        """The decision_maker lens produces trigger + evidence."""
        deal = store.get_deal("D001")
        assert deal is not None
        acts = store.activities_for_deal("D001")
        lens = next(l for l in LENSES if l.name == "decision_maker")

        exp = explain_lens(
            lens_name=lens.name, lens_cues=lens.cues, lens_tags=lens.tags,
            observation=lens.observation,
            note="担当者は前向きで好感触",
            deal=deal, activities=acts, today=TODAY,
        )
        assert isinstance(exp, Explanation)
        assert exp.recommendation_id == "lens:decision_maker"
        assert len(exp.triggers) == 1
        assert exp.triggers[0].rule_type == "lens"
        assert "absent_cues" in exp.triggers[0].matched_data
        # Principle should be P006 (DM-related, backed by 2 interviews)
        if exp.principle_id:
            assert exp.principle_id in ("P003", "P006")

    def test_lens_without_deal(self):
        """Lens explanation works with note alone (no deal context)."""
        lens = next(l for l in LENSES if l.name == "budget")
        exp = explain_lens(
            lens_name=lens.name, lens_cues=lens.cues, lens_tags=lens.tags,
            observation=lens.observation,
            note="初回訪問で好印象",
            deal=None, activities=None, today=TODAY,
        )
        assert isinstance(exp, Explanation)
        # No evidence when there's no deal
        assert len(exp.evidence) == 0
        # But triggers still fire
        assert len(exp.triggers) == 1


class TestExplainSignal:
    """Signal explanations trace to source SPR fields."""

    def test_staleness_signal(self):
        sig = Signal(name="staleness", points=30,
                     reason="45日間接触なし(目安14日の2倍超)")
        deal = store.get_deal("D001")
        assert deal is not None
        acts = store.activities_for_deal("D001")

        exp = explain_signal(sig, deal, acts, today=TODAY)
        assert exp.recommendation_id == "signal:staleness"
        assert len(exp.triggers) == 1
        assert exp.triggers[0].matched_data["points"] == 30

    def test_missing_dm_signal(self):
        sig = Signal(name="missing_dm", points=15, reason="決裁者が未特定")
        deal = store.get_deal("D001")
        assert deal is not None
        acts = store.activities_for_deal("D001")

        exp = explain_signal(sig, deal, acts, today=TODAY)
        assert exp.recommendation_id == "signal:missing_dm"
        assert len(exp.evidence) >= 1
        assert "business_card_info" in exp.evidence[0].field


class TestExplainPresence:
    """Presence-detector explanations."""

    def test_stall_presence(self):
        exp = explain_presence(
            "stall", "検討します",
            "お客様は検討しますと言っていました",
            None, None, TODAY,
        )
        assert exp.recommendation_id == "presence:stall"
        assert exp.triggers[0].matched_data["word"] == "検討します"
        assert exp.principle_id == "P001"

    def test_competitor_presence(self):
        exp = explain_presence(
            "competitor", "競合",
            "競合製品と比較検討中",
            None, None, TODAY,
        )
        assert exp.recommendation_id == "presence:competitor"
        assert exp.principle_id == "P009"


class TestExplainCoachingIssue:
    """Coaching issue explanations for the manager workspace."""

    def test_missing_dm_issue(self):
        deal = store.get_deal("D001")
        assert deal is not None
        acts = store.activities_for_deal("D001")

        exp = explain_coaching_issue(
            "missing_decision_maker", {"reports": 3},
            deal, acts, today=TODAY,
        )
        assert "issue:missing_decision_maker" in exp.recommendation_id
        assert exp.principle_id == "P006"
        assert len(exp.triggers) == 1
        assert len(exp.evidence) >= 1

    def test_premature_discount_issue(self):
        deal = store.get_deal("D001")
        assert deal is not None
        acts = store.activities_for_deal("D001")

        exp = explain_coaching_issue(
            "premature_discount", {"rate": 15},
            deal, acts, today=TODAY,
        )
        assert exp.principle_id == "P002"
        assert exp.evidence[0].field == "discount_rate"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestReviewNoteIntegration:
    """review_note() now returns explanations alongside coaching content."""

    def test_explanations_populated(self):
        """A note that triggers lenses should produce explanations."""
        r = review_note("担当者は前向きで好感触", today=TODAY)
        assert isinstance(r, CoachReview)
        assert len(r.explanations) > 0
        for exp in r.explanations:
            assert isinstance(exp, Explanation)
            assert exp.recommendation_id
            assert len(exp.triggers) > 0

    def test_explanations_with_deal(self):
        """Explanations should include signal evidence when a deal is supplied."""
        deal = store.get_deal("D001")
        acts = store.activities_for_deal("D001")
        r = review_note(
            "担当者は前向き", deal=deal, notes=acts, today=TODAY,
        )
        # Should have lens explanations + signal explanations
        lens_exps = [e for e in r.explanations if e.recommendation_id.startswith("lens:")]
        signal_exps = [e for e in r.explanations if e.recommendation_id.startswith("signal:")]
        assert len(lens_exps) > 0
        if signal_exps:
            assert all(len(e.evidence) > 0 for e in signal_exps)

    def test_explanation_serialization(self):
        """Explanations should serialize cleanly to dicts."""
        r = review_note("検討しますと言われた", today=TODAY)
        for exp in r.explanations:
            d = exp.to_dict()
            assert isinstance(d, dict)
            assert "triggers" in d
            assert "evidence" in d
            assert "similar_cases" in d
            assert "outcome_stats" in d  # may be None


class TestCoachingWorkspaceIntegration:
    """coaching_workspace() cards should now carry explanations."""

    def test_cards_have_explanations(self):
        ws = coaching_workspace(today=TODAY)
        cards = ws.get("needs_coaching", [])
        if cards:
            # At least some cards should have explanations
            has_exp = [c for c in cards if c.get("explanation")]
            assert len(has_exp) > 0
            # Verify shape
            for c in has_exp:
                exp = c["explanation"]
                assert "triggers" in exp
                assert "evidence" in exp
                assert "similar_cases" in exp
                assert "outcome_stats" in exp
                assert "confidence" in exp


class TestGroundingContract:
    """Every statistic and case comes from real data, never invented."""

    def test_similar_cases_are_real_deals(self):
        """Every similar case returned should exist in the store."""
        r = review_note("担当者は前向き", today=TODAY)
        for exp in r.explanations:
            for case in exp.similar_cases:
                deal = store.get_deal(case.deal_id)
                assert deal is not None, f"Similar case {case.deal_id} not in store"

    def test_outcome_stats_match_real_data(self):
        """Manually verify one stat against direct query."""
        from senpai.coach.cases import _has_decision_maker

        # Count deals without DM directly
        won, lost = 0, 0
        for d in store.all_deals():
            rank = d.get("order_rank")
            if rank not in (config.WON_RANKS | config.DEAD_RANKS):
                continue
            acts = store.activities_for_deal(d["deal_id"])
            if not _has_decision_maker(acts):
                if rank in config.WON_RANKS:
                    won += 1
                else:
                    lost += 1

        stats = compute_outcome_stats(
            lambda d, acts: not _has_decision_maker(acts),
            "テスト", "test",
        )
        if won + lost >= 5:
            assert stats is not None
            assert stats.won == won
            assert stats.lost == lost
