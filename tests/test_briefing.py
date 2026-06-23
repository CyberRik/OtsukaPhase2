"""Tests for the morning briefing / next-best-action worklist.

Hermetic: pure store + scoring, no model/network. SENPAI_TODAY is pinned in
conftest so the committed seed yields a deterministic briefing.
"""
from __future__ import annotations

from datetime import date

from senpai import briefing
from senpai.briefing import ActionItem, morning_briefing, format_briefing
from senpai.tools import impl

TODAY = date(2026, 6, 16)


def test_briefing_returns_action_items_for_a_rep():
    items = morning_briefing(rep_id="R12", today=TODAY)
    assert items, "R12 should have at least one open deal needing action"
    assert all(isinstance(it, ActionItem) for it in items)
    # every item carries a concrete action and a reason
    assert all(it.action and it.reason for it in items)


def test_items_sorted_by_priority_descending():
    items = morning_briefing(rep_id="R12", today=TODAY)
    priorities = [it.priority for it in items]
    assert priorities == sorted(priorities, reverse=True)


def test_overdue_deal_is_surfaced_with_reconfirm_action():
    # D001 is past its expected_order_date while still open → top of R12's list.
    items = morning_briefing(rep_id="R12", today=TODAY)
    d001 = next((it for it in items if it.deal_id == "D001"), None)
    assert d001 is not None
    assert d001.due == "overdue"
    assert "受注時期" in d001.action


def test_healthy_deals_dropped_by_default_but_kept_when_requested():
    lean = morning_briefing(rep_id="R12", today=TODAY, include_healthy=False)
    full = morning_briefing(rep_id="R12", today=TODAY, include_healthy=True, limit=0)
    # include_healthy never returns fewer items than the lean default
    assert len(full) >= len(lean)
    # the lean list keeps only deals needing attention
    assert all(it.band != "green" or it.due for it in lean)


def test_limit_is_respected():
    items = morning_briefing(today=TODAY, limit=3)
    assert len(items) <= 3


def test_format_briefing_is_a_nonempty_string():
    out = format_briefing(morning_briefing(rep_id="R12", today=TODAY), rep_id="R12")
    assert isinstance(out, str) and out.strip()
    assert "本日の優先アクション" in out


def test_empty_briefing_has_friendly_message():
    assert "ありません" in format_briefing([], rep_id="R12", today=TODAY)


def test_tool_dispatch_runs_and_returns_string():
    out = impl.dispatch("morning_briefing", {"rep_id": "R12", "limit": 5})
    assert isinstance(out, str) and not out.startswith("[error]")
    assert "D001" in out  # the overdue anchor shows up


def test_tool_handles_bad_limit_gracefully():
    out = impl.dispatch("morning_briefing", {"rep_id": "R12", "limit": "oops"})
    assert isinstance(out, str) and not out.startswith("[error]")
