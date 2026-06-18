"""Unit tests for the deterministic deal-health scorer (no GPU, no model).

Uses the real SPR fields (order_rank, rank_updated_at, expected_order_date /
days_until_order) and sales_activities with daily_report / business_card_info.
"""
from __future__ import annotations

from datetime import timedelta

from senpai import config
from senpai.health.scoring import score_deal

TODAY = config.today()


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _deal(**over):
    base = {
        "deal_id": "D999",
        "order_rank": "3_A",
        "initial_order_rank": "3_A",
        "rank_updated_at": _iso(10),
        "rank_first_registered_at": _iso(30),
        "expected_order_date": _iso(-20),     # 20 days in the future
        "days_until_order": 20,
        "total_order_amount": 500000,
    }
    base.update(over)
    return base


def _act(days_ago, text="フォロー実施。", card="情報システム部 部長"):
    return {"activity_date": _iso(days_ago), "activity_type": "002_Daily Report",
            "daily_report": text, "business_card_info": card}


def test_healthy_deal_is_green():
    res = score_deal(_deal(), [_act(3, "デモを実施。前向き。")], today=TODAY)
    assert res.band == "green"
    assert res.score < config.YELLOW_THRESHOLD


def test_dead_deal_is_red():
    """Stale + rank stagnation + order date passed + no DM + stall language."""
    deal = _deal(
        order_rank="2_A+", initial_order_rank="2_A+",
        rank_updated_at=_iso(60),
        expected_order_date=_iso(25), days_until_order=-25,   # already past
    )
    acts = [_act(45, "担当者より「検討します」との返答。", card="")]   # no DM, stall
    res = score_deal(deal, acts, today=TODAY)
    assert res.band == "red"
    assert res.score >= config.RED_THRESHOLD
    fired = {s.name for s in res.signals}
    assert {"staleness", "order_date_past", "missing_dm",
            "stall_language", "low_activity"} <= fired


def test_order_date_past_signal_fires():
    deal = _deal(expected_order_date=_iso(5), days_until_order=-5)
    res = score_deal(deal, [_act(3)], today=TODAY)
    assert any(s.name == "order_date_past" for s in res.signals)


def test_rank_regression_fires_and_caps():
    deal = _deal(order_rank="4_B", initial_order_rank="2_A+")   # dropped 2 ranks
    res = score_deal(deal, [_act(2)], today=TODAY)
    reg = next(s for s in res.signals if s.name == "rank_regression")
    assert reg.points == 20      # (4-2)*10, capped at 20


def test_missing_dm_only_in_strong_rank():
    weak = _deal(order_rank="6_P", initial_order_rank="6_P",
                 rank_updated_at=_iso(3))
    res = score_deal(weak, [_act(2, card="")], today=TODAY)   # no DM, but weak rank
    assert not any(s.name == "missing_dm" for s in res.signals)


def test_every_signal_has_a_reason():
    deal = _deal(order_rank="2_A+", rank_updated_at=_iso(60),
                 expected_order_date=_iso(10), days_until_order=-10)
    res = score_deal(deal, [_act(60, "「予算が」厳しい", card="")], today=TODAY)
    assert res.signals
    assert all(s.reason for s in res.signals)
