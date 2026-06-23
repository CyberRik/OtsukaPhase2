"""Tests for the longitudinal progress engine (senpai.coach.progress)."""
from __future__ import annotations

from datetime import date

from senpai.coach.progress import rep_progress
from senpai.data import gen_seed

TODAY = date(2026, 6, 16)


def _find(improving: bool):
    return next(e for e, s in gen_seed.REP_SKILL.items()
               if s["improving"] is improving and "discovery" in s["weaknesses"]
               and s["role"] == "junior")


def test_progress_shape():
    p = rep_progress("R05", today=TODAY, windows=4)
    assert len(p["windows"]) == 4
    assert len(p["series"]) == 4
    assert "coaching_acted_on" in p
    for s in p["series"]:
        assert s["window"].startswith("FY")
        assert s["active_deals"] >= 0


def test_improving_rep_trends_down_on_its_weakness():
    emp = _find(improving=True)        # a seeded "improving" discovery-weak rep
    p = rep_progress(emp, today=TODAY)
    # their headline should not be "worsening", and discovery should improve or be flat
    assert p["headline"] in ("改善傾向", "横ばい", "データ不足")
    assert p["trends"].get("weak_customer_discovery") in ("improving", "flat")


def test_non_improving_rep_does_not_spuriously_improve_on_weakness():
    emp = _find(improving=False)
    p = rep_progress(emp, today=TODAY)
    # a non-improving discovery-weak rep should not show discovery improving
    assert p["trends"].get("weak_customer_discovery") in ("worsening", "flat")


def test_long_inactivity_excluded_from_trend():
    # staleness is a replay artifact, deliberately not tracked
    from senpai.coach import progress
    assert "long_inactivity" not in progress._TRACK


def test_acted_on_join_present():
    p = rep_progress("R12", today=TODAY)
    a = p["coaching_acted_on"]
    assert set(a) == {"total", "resolved", "rate"}
    if a["total"]:
        assert 0.0 <= a["rate"] <= 1.0
