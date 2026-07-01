#!/usr/bin/env python3
"""Seed a login account for every existing rep and dump the credentials to a file.

So you can log in as ANY rep (juniors → junior UI, seniors/experts → manager UI)
to demo features with real data. Passwords are a shared `demo123`; usernames are
the romaji of the rep's name (falling back to the lowercased employee_id when the
romaji library isn't available).

    .venv/bin/python scripts/seed_rep_logins.py

Idempotent: skips reps that already have an account. Writes rep_credentials.txt
(gitignored — it holds plaintext passwords). Re-run after wiping the ingested
overlay (which is where the accounts live).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from senpai.api import auth
from senpai.data import store

PASSWORD = "demo123"
OUT_FILE = Path(__file__).resolve().parent.parent / "rep_credentials.txt"

try:  # kanji → romaji; optional so the script never hard-fails
    import pykakasi

    _KKS = pykakasi.kakasi()
except Exception:  # noqa: BLE001
    _KKS = None


def romaji_username(name: str, employee_id: str) -> str:
    """Lowercase romaji of the name (ascii only); employee_id if unavailable."""
    if _KKS is not None:
        romaji = "".join(seg.get("hepburn", "") for seg in _KKS.convert(name))
        romaji = re.sub(r"[^a-z0-9]", "", romaji.lower())
        if romaji:
            return romaji
    return employee_id.lower()


def account_role(rep_role: str) -> str:
    """Rep role → app account role: juniors get the junior UI, everyone else the
    manager UI."""
    return "junior" if rep_role == "junior" else "manager"


def main() -> int:
    rows: list[tuple[str, str, str, str]] = []  # username, employee_id, role, name
    used: set[str] = set()
    created = skipped = 0

    for rep in store.all_reps():
        eid, name = rep["employee_id"], rep.get("name", rep["employee_id"])
        role = account_role(rep.get("role", "junior"))
        username = romaji_username(name, eid)
        if username in used or auth.username_exists(username):
            username = f"{username}_{eid.lower()}"  # dedup collisions
        used.add(username)

        try:
            auth.create_user(username, PASSWORD, role, employee_id=eid)
            created += 1
        except ValueError:
            skipped += 1  # already seeded
        rows.append((username, eid, role, name))

    lines = ["# Rep logins — password is 'demo123' for all. Gitignored (plaintext).",
             f"# {'username':<20} {'emp':<5} {'role':<8} name", ""]
    for username, eid, role, name in sorted(rows, key=lambda r: r[1]):
        lines.append(f"{username:<22} {eid:<5} {role:<8} {name}")
    OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"seeded {created} account(s), skipped {skipped} existing; "
          f"credentials → {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
