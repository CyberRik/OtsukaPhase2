"""Unit tests for report-reliability flags (no GPU, no model).

Uses the real SPR fields + sales_activities (daily_report, business_card_info).
"""
from __future__ import annotations

from datetime import timedelta

from senpai import config
from senpai.health.flags import deal_flags

TODAY = config.today()


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _act(days_ago, text="提案提出", card="総務部 課長"):
    return {"activity_date": _iso(days_ago), "activity_type": "002_Daily Report",
            "daily_report": text, "business_card_info": card}


def _clean_deal(**over):
    """A deal with NO flags firing by default."""
    base = {
        "deal_id": "D999",
        "order_rank": "3_A",
        "initial_order_rank": "3_A",
        "rank_updated_at": _iso(5),
        "expected_order_date": _iso(-20),
        "days_until_order": 20,
        "total_order_amount": 500000,
    }
    base.update(over)
    return base


def _names(flags):
    return {f.name for f in flags}


def test_clean_deal_has_no_flags():
    deal = _clean_deal()
    assert deal_flags(deal, [_act(5)], health_band="green", today=TODAY) == []


def test_close_date_passed_fires():
    deal = _clean_deal(expected_order_date=_iso(5), days_until_order=-5)
    flags = deal_flags(deal, [_act(5)], today=TODAY)
    assert "close_date_passed" in _names(flags)


def test_stale_active_fires():
    deal = _clean_deal()
    flags = deal_flags(deal, [_act(45)], today=TODAY)
    assert "stale_active" in _names(flags)


def test_missing_fields_fires():
    deal = _clean_deal(total_order_amount=0)
    flags = deal_flags(deal, [_act(5, card="")], today=TODAY)   # no DM + no amount
    assert "missing_fields" in _names(flags)


def test_optimism_mismatch_fires():
    deal = _clean_deal(order_rank="2_A+")
    flags = deal_flags(deal, [_act(5)], health_band="red", today=TODAY)
    assert "optimism_mismatch" in _names(flags)


def test_optimism_mismatch_silent_when_band_green():
    deal = _clean_deal(order_rank="2_A+")
    flags = deal_flags(deal, [_act(5)], health_band="green", today=TODAY)
    assert "optimism_mismatch" not in _names(flags)


def test_unsupported_rank_fires_without_supporting_activity():
    deal = _clean_deal(rank_updated_at=_iso(40))
    flags = deal_flags(deal, [_act(5)], today=TODAY)   # activity far from rank update
    assert "unsupported_rank" in _names(flags)


def test_unsupported_rank_silent_with_supporting_activity():
    deal = _clean_deal(rank_updated_at=_iso(5))
    flags = deal_flags(deal, [_act(5, "提案提出")], today=TODAY)
    assert "unsupported_rank" not in _names(flags)
