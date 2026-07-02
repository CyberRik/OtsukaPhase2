"""Simple demo signup/login — a JSON-file user store with salted password hashing.

This is intentionally minimal: no email verification, no rate limiting, no refresh
tokens. It exists so the web app has *real* accounts (persisted, hashed
credentials) instead of the two hardcoded frontend demo logins. Passwords are
stretched with PBKDF2-HMAC-SHA256 and never stored in the clear.

Users live in the gitignored ingested overlay (``config.INGESTED_DIR``), so real
signups never touch the committed seed — same pattern as saved sales activities.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Literal

from senpai import config

Role = Literal["junior", "manager"]

USERS_PATH = config.INGESTED_DIR / "users.json"
_PBKDF2_ROUNDS = 120_000


def _load() -> dict[str, dict]:
    if not USERS_PATH.exists():
        return {}
    return json.loads(USERS_PATH.read_text(encoding="utf-8"))


def _save(users: dict[str, dict]) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USERS_PATH.write_text(
        json.dumps(users, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _hash(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ROUNDS
    )
    return dk.hex()


def _norm(username: str) -> str:
    """Lookup key: usernames are case-insensitive and trimmed."""
    return username.strip().lower()


def _public(rec: dict) -> dict:
    """The user shape safe to return to the client (no password material).

    ``employee_id`` ties the account to a rep in the seed data so the experience
    (deals, growth, coaching) resolves to a real identity. ``role`` is the account
    role — 'junior' or 'manager' — which picks which UI the app loads."""
    return {
        "username": rec["username"],
        "role": rec["role"],
        "employee_id": rec.get("employee_id"),
    }


def list_users() -> list[dict]:
    """Every account in public shape (no password material) — for the admin
    portal's account listing."""
    return [_public(rec) for rec in _load().values()]


def username_exists(username: str) -> bool:
    """Whether an account with this username already exists (case-insensitive).
    Used to pre-check a signup before creating a rep, so a taken username can't
    leave an orphan rep behind."""
    return _norm(username) in _load()


def create_user(
    username: str,
    password: str,
    role: Role,
    employee_id: str | None = None,
) -> dict:
    """Register a new account. Raises ``ValueError`` if inputs are blank, the
    role is invalid, or the username is taken. Returns the public user.

    ``employee_id`` links the account to a rep — a junior's own newly-created rep,
    or an existing rep when seeding logins. Each account maps to a distinct rep,
    so no cross-account rep sharing needs guarding."""
    key = _norm(username)
    if not key or not password:
        raise ValueError("username and password are required")
    if role not in ("junior", "manager"):
        raise ValueError("role must be 'junior' or 'manager'")
    users = _load()
    if key in users:
        raise ValueError("username already taken")
    salt = secrets.token_hex(16)
    users[key] = {
        "username": username.strip(),
        "role": role,
        "employee_id": employee_id,
        "salt": salt,
        "password_hash": _hash(password, salt),
    }
    _save(users)
    return _public(users[key])


def verify_user(username: str, password: str) -> dict | None:
    """Return the public user dict if the credentials match, else ``None``."""
    rec = _load().get(_norm(username))
    if not rec:
        return None
    if not secrets.compare_digest(_hash(password, rec["salt"]), rec["password_hash"]):
        return None
    return _public(rec)


def issue_token() -> str:
    """An opaque session token handed to the client on signup/login. Nothing
    enforces it yet (no endpoints are protected), but it gives the frontend a
    real credential to store and a hook for future auth checks."""
    return secrets.token_urlsafe(24)
