"""Tests for the rep coaching profile engine (senpai.coach.profile)."""
from __future__ import annotations

from datetime import date

from senpai.coach.profile import rep_coaching_profile, team_coaching_profiles
from senpai.coaching import ISSUE_PRIORITY
from senpai.data import gen_seed

TODAY = date(2026, 6, 16)

_PRI = {"high": 0, "medium": 1, "low": 2}


def test_profile_shape_and_grounding():
    p = rep_coaching_profile("R12", today=TODAY)
    assert p["employee_id"] == "R12" and p["name"]
    assert p["open_deals"] > 0
    assert p["weaknesses"], "a junior should surface at least one recurring weakness"
    for w in p["weaknesses"]:
        assert w["count"] >= 1
        assert w["example_deals"], "weakness must be grounded in real deals"
        assert w["action"]


def test_weaknesses_ranked_by_severity_then_count():
    p = rep_coaching_profile("R12", today=TODAY)
    keys = [(_PRI[ISSUE_PRIORITY.get(w["issue"], "low")], -w["count"]) for w in p["weaknesses"]]
    assert keys == sorted(keys), "weaknesses not ordered by severity then frequency"
    # the headline focus is the first (most important) weakness
    assert p["development_focus"] == p["weaknesses"][0]["issue"]


def test_decision_maker_weak_rep_surfaces_that_issue():
    # A *non-improving* decision-maker-weak rep still has the gap on current deals
    # (improving reps legitimately recover it, so we exclude them here).
    target = next(e for e, s in gen_seed.REP_SKILL.items()
                  if "decision_maker" in s["weaknesses"]
                  and s["role"] == "junior" and not s["improving"])
    p = rep_coaching_profile(target, today=TODAY)
    issues = {w["issue"] for w in p["weaknesses"]}
    # the engine should rediscover the seeded weakness as a recurring issue
    assert "missing_decision_maker" in issues


def test_principle_and_case_attached_for_dm_issue():
    p = rep_coaching_profile("R12", today=TODAY)
    dm = next((w for w in p["weaknesses"] if w["issue"] == "missing_decision_maker"), None)
    if dm:  # R12 is dm-weak in the seed, but guard anyway
        assert dm["principle"] and dm["principle"]["id"].startswith("P")
        assert dm["case"] and dm["case"]["outcome"] in ("won", "lost")


def test_profile_is_deterministic():
    a = rep_coaching_profile("R12", today=TODAY)
    b = rep_coaching_profile("R12", today=TODAY)
    assert a["development_focus"] == b["development_focus"]
    assert [w["issue"] for w in a["weaknesses"]] == [w["issue"] for w in b["weaknesses"]]


def test_talking_points_and_threads():
    p = rep_coaching_profile("R12", today=TODAY)
    assert p["talking_points"], "a 1:1 needs talking points"
    assert "total" in p["threads"]


def test_team_rollup_sorted_by_attention():
    rows = team_coaching_profiles(today=TODAY)
    assert rows and all(r["open_deals"] > 0 for r in rows)
    risk = [(r["at_risk"], r["avg_risk"]) for r in rows]
    assert risk == sorted(risk, reverse=True), "team rollup not sorted by attention needed"


def test_coach_api_endpoints():
    from fastapi.testclient import TestClient
    from senpai.api.server import app
    c = TestClient(app)
    assert c.get("/api/coach/rep-profile/R12").json()["employee_id"] == "R12"
    assert "reps" in c.get("/api/coach/rep-profiles").json()
    prog = c.get("/api/coach/rep-progress/R05").json()
    assert len(prog["series"]) == 4
    threads = c.get("/api/coach/threads?rep_id=R12").json()["threads"]
    assert all(t["employee_id"] == "R12" for t in threads)
