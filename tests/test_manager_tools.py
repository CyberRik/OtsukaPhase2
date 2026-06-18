"""Unit tests for the manager-facing tools + web_search (no GPU, no model).

Pins SENPAI_TODAY so the seed-derived counts are deterministic regardless of the
real date. Expected aggregates are computed from the same engine the tools use,
so these assert the tools *format/aggregate* correctly rather than re-hardcoding
magic numbers that drift if the seed changes.
"""
from __future__ import annotations

import os

os.environ.setdefault("SENPAI_TODAY", "2026-06-16")  # before any config.today() call

from senpai.data import store
from senpai.tools import impl


def test_list_at_risk_defaults_to_red_and_sorted():
    import re
    out = impl.list_at_risk_deals(limit=10)
    assert "D001" in out                 # a seeded dead deal
    assert "🟢" not in out and "🟡" not in out   # default band is red only
    # risk scores must be non-increasing down the list (worst-first).
    scores = [int(x) for x in re.findall(r"リスク(\d+)", out)]
    assert scores == sorted(scores, reverse=True)


def test_list_at_risk_band_yellow_widens():
    red = impl.list_at_risk_deals(band="red")
    wide = impl.list_at_risk_deals(band="yellow", limit=100)
    assert wide.count("D") >= red.count("D")   # yellow includes red + yellow


def test_pipeline_overview_counts_match_store():
    out = impl.team_pipeline_overview()
    expected_open = len(store.open_deals())
    expected_red = sum(1 for _d, res, _f in impl._score_open_deals() if res.band == "red")
    assert f"{expected_open}件" in out
    assert f"🔴{expected_red}" in out
    assert "信頼性フラグ" in out


def test_report_digest_groups_flagged_deals():
    out = impl.team_report_digest()
    assert "ダイジェスト" in out
    assert "D003" in out                 # a known flagged (close-date-passed) deal


def test_coaching_focus_rolls_up_per_rep():
    out = impl.rep_coaching_focus()
    assert "コーチング" in out
    assert "伊藤翔" in out
    assert "平均リスク" in out


def test_draft_message_is_editable_and_unsent():
    out = impl.draft_message(to="伊藤さん", about="D001の進捗", deal_id="D001")
    assert out                            # non-empty
    assert "送信はされません" in out      # human-in-the-loop, never sent
    assert "村田印刷" in out              # pulled deal context


def test_web_search_works_offline():
    out = impl.web_search("製造業 IT投資")
    assert isinstance(out, str) and "検索結果" in out


def test_summarize_reports_still_works():
    out = impl.summarize_reports("R05")
    assert "要約" in out
    assert "信頼性フラグ" in out
