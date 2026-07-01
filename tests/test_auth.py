"""Signup/login for the simple demo auth (senpai.api.auth + /api/auth/*).

Hermetic: points the user store at a tmp file so the suite never touches the
real ingested overlay.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import senpai.api.auth as auth
import senpai.api.server as server
from senpai.growth import junior_reps


@pytest.fixture(autouse=True)
def _tmp_users(tmp_path, monkeypatch):
    # Point the store at a throwaway file, then re-seed the demo accounts into
    # it (the import-time seed wrote to the real overlay before this patch).
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    server._seed_demo_users()


@pytest.fixture()
def client():
    return TestClient(server.app)


def _a_junior() -> str:
    return junior_reps()[0]["employee_id"]


def test_signup_manager_creates_account_and_returns_role_and_token(client):
    res = client.post("/api/auth/signup",
                      json={"username": "Alice", "password": "pw123", "role": "manager"})
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "Alice"
    assert body["role"] == "manager"
    assert body["employee_id"] is None  # managers see the whole team
    assert body["token"]


def test_junior_signup_adopts_seed_rep(client):
    eid = _a_junior()
    res = client.post("/api/auth/signup",
                      json={"username": "newbie", "password": "pw", "role": "junior",
                            "employee_id": eid})
    assert res.status_code == 200
    assert res.json()["employee_id"] == eid
    # And the identity persists on login.
    login = client.post("/api/auth/login", json={"username": "newbie", "password": "pw"})
    assert login.json()["employee_id"] == eid


def test_junior_signup_requires_valid_rep(client):
    missing = client.post("/api/auth/signup",
                          json={"username": "x", "password": "pw", "role": "junior"})
    assert missing.status_code == 400
    bogus = client.post("/api/auth/signup",
                        json={"username": "y", "password": "pw", "role": "junior",
                              "employee_id": "R999"})
    assert bogus.status_code == 400


def test_juniors_roster_endpoint(client):
    res = client.get("/api/reps/juniors")
    assert res.status_code == 200
    juniors = res.json()["juniors"]
    assert juniors and all("employee_id" in j and "name" in j for j in juniors)


def test_login_succeeds_with_correct_password(client):
    client.post("/api/auth/signup", json={"username": "bob", "password": "secret",
                                           "role": "junior", "employee_id": _a_junior()})
    res = client.post("/api/auth/login", json={"username": "bob", "password": "secret"})
    assert res.status_code == 200
    assert res.json()["role"] == "junior"


def test_login_is_case_insensitive_on_username(client):
    client.post("/api/auth/signup", json={"username": "Carol", "password": "pw", "role": "manager"})
    res = client.post("/api/auth/login", json={"username": "CAROL", "password": "pw"})
    assert res.status_code == 200


def test_duplicate_signup_rejected(client):
    client.post("/api/auth/signup", json={"username": "dave", "password": "pw", "role": "manager"})
    res = client.post("/api/auth/signup", json={"username": "dave", "password": "other", "role": "manager"})
    assert res.status_code == 400
    assert "taken" in res.json()["detail"]


def test_login_wrong_password_rejected(client):
    client.post("/api/auth/signup", json={"username": "erin", "password": "right", "role": "manager"})
    res = client.post("/api/auth/login", json={"username": "erin", "password": "wrong"})
    assert res.status_code == 401


def test_login_unknown_user_rejected(client):
    res = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert res.status_code == 401


def test_password_is_not_stored_in_clear(client, tmp_path):
    client.post("/api/auth/signup", json={"username": "frank", "password": "topsecret", "role": "manager"})
    stored = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "topsecret" not in stored
    assert "password_hash" in stored


def test_demo_users_seeded_and_junior_maps_to_a_rep(client):
    """The built-in demo logins still work through the real auth path, and the
    junior demo account resolves to a seed junior rep."""
    j = client.post("/api/auth/login", json={"username": "junior", "password": "demo123"})
    assert j.status_code == 200
    assert j.json()["employee_id"] in {r["employee_id"] for r in junior_reps()}
    m = client.post("/api/auth/login", json={"username": "manager", "password": "demo123"})
    assert m.status_code == 200
    assert m.json()["employee_id"] is None
