"""Signup/login for the demo auth. Junior signup CREATES a new seed-shape rep
assigned to an existing manager; managers are the existing senior/expert reps.

Hermetic: both the user store (auth.USERS_PATH) and the rep overlay
(config.INGESTED_DIR) point at a throwaway dir, so the suite never mutates the
real overlay. store.reload() clears the cache around each test.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import senpai.api.auth as auth
import senpai.api.server as server
from senpai import config
from senpai.data import store
from senpai.growth import junior_reps
from scripts.seed_rep_logins import account_role, romaji_username


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(config, "INGESTED_DIR", tmp_path)
    store.reload()
    yield
    store.reload()


@pytest.fixture()
def client():
    return TestClient(server.app)


def _a_manager() -> dict:
    return next(r for r in store.all_reps() if r.get("role") in ("senior", "expert"))


def _a_coach() -> str:
    """An existing manager that already has thread-based coachees."""
    return next(t["manager_id"] for t in store.all_coaching_threads() if t.get("manager_id"))


def _signup(client, **over):
    mgr = _a_manager()
    body = {"username": "newbie", "password": "pw", "name": "新人 太郎",
            "manager_id": mgr["employee_id"]}
    body.update(over)
    return client.post("/api/auth/signup", json=body)


# --- signup creates a real new rep -----------------------------------------
def test_signup_creates_new_junior_rep(client):
    mgr = _a_manager()
    before = {r["employee_id"] for r in store.all_reps()}
    res = _signup(client, manager_id=mgr["employee_id"])
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "junior"
    new_id = body["employee_id"]
    assert new_id not in before  # a brand-new id, not an adopted one

    rep = store.get_rep(new_id)
    assert rep and rep["role"] == "junior"
    assert rep["reports_to"] == mgr["employee_id"]
    assert rep["department"] == mgr["department"]  # inherited from the manager
    assert rep["division"] == mgr["division"]
    assert rep["employee_id"] in {r["employee_id"] for r in junior_reps()}


def test_signup_persists_identity_on_login(client):
    res = _signup(client, username="alice")
    new_id = res.json()["employee_id"]
    login = client.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert login.status_code == 200
    assert login.json()["employee_id"] == new_id


def test_signup_requires_a_valid_manager(client):
    a_junior = next(r["employee_id"] for r in store.all_reps() if r["role"] == "junior")
    assert _signup(client, manager_id=a_junior).status_code == 400   # not a manager
    assert _signup(client, manager_id="R999").status_code == 400     # nonexistent


def test_signup_requires_fields(client):
    assert _signup(client, name="").status_code == 400
    assert _signup(client, username="").status_code == 400


def test_duplicate_username_rejected_without_orphan_rep(client):
    assert _signup(client, username="dup").status_code == 200
    n_reps = len(store.all_reps())
    assert _signup(client, username="dup").status_code == 400
    assert len(store.all_reps()) == n_reps  # the taken username created no rep


# --- manager pool + team roster --------------------------------------------
def test_manager_pool_lists_only_senior_and_expert(client):
    managers = client.get("/api/reps/managers").json()["managers"]
    assert managers
    assert all(m["role"] in ("senior", "expert") for m in managers)


def test_assigned_junior_shows_in_managers_team(client):
    mgr = _a_manager()["employee_id"]
    new_id = _signup(client, manager_id=mgr).json()["employee_id"]
    assert new_id in store.team_of(mgr)
    roster = client.get(f"/api/coach/team?manager={mgr}").json()["reps"]
    row = next((r for r in roster if r["employee_id"] == new_id), None)
    assert row is not None and row["open_deals"] == 0  # visible despite no deals


def test_team_endpoint_empty_without_manager(client):
    assert client.get("/api/coach/team").json()["reps"] == []


# --- manager scoping (existing coach) --------------------------------------
def test_rep_profiles_scoped_to_team(client):
    coach = _a_coach()
    team = store.team_of(coach)
    scoped = client.get(f"/api/coach/rep-profiles?manager={coach}").json()["reps"]
    assert all(r["employee_id"] in team for r in scoped)
    everyone = client.get("/api/coach/rep-profiles").json()["reps"]
    assert len(scoped) <= len(everyone)


def test_dashboard_scoped_to_team(client):
    coach = _a_coach()
    team_names = {store.rep_name(e) for e in store.team_of(coach)}
    scoped = client.get(f"/api/dashboard?manager={coach}").json()
    assert all(d["rep"] in team_names for d in scoped["deals"])


# --- credentials / empty-rep safety ----------------------------------------
def test_login_wrong_password_and_unknown_user(client):
    _signup(client, username="erin")
    assert client.post("/api/auth/login",
                       json={"username": "erin", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"username": "ghost", "password": "x"}).status_code == 401


def test_new_reps_endpoints_do_not_crash_on_empty_data(client):
    new_id = _signup(client).json()["employee_id"]
    assert client.get(f"/api/growth?rep={new_id}").status_code == 200
    assert client.get(f"/api/coach/rep-profile/{new_id}").status_code == 200


def test_rep_login_helpers():
    assert account_role("junior") == "junior"
    assert account_role("senior") == "manager"
    assert account_role("expert") == "manager"
    # Fallback path is deterministic even if romaji is unavailable.
    assert romaji_username("", "R07") == "r07"
