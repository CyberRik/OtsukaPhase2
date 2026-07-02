#!/usr/bin/env python3
"""Backfill `reports_to` for every rep that lacks one, so the whole org is
reassignable from the admin portal.

The committed seed reps (R01–R24) have no `reports_to` — their manager is only
*implied* by coaching threads (`coaching_threads.json`, each thread has an
`employee_id` rep and a `manager_id`). This derives the most frequent thread
manager per rep and persists it via `store.set_reports_to`, which writes the
gitignored reps overlay (seed on disk is never touched).

    .venv/bin/python scripts/backfill_reports_to.py

Idempotent: reps that already have a `reports_to` are skipped, and reps with no
coaching threads are left unassigned (they surface as "Unassigned" in the admin
org view and can be placed by hand there). Re-run after wiping the ingested
overlay.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from senpai.data import store


def derive_manager(employee_id: str) -> str | None:
    """The rep's most common thread `manager_id` (ties broken by first seen),
    restricted to real assignable managers (senior/expert)."""
    counts: Counter[str] = Counter()
    for t in store.coaching_threads_for_rep(employee_id):
        mid = t.get("manager_id")
        if not mid or mid == employee_id:
            continue
        mgr = store.get_rep(mid)
        if mgr is not None and mgr.get("role") in ("senior", "expert"):
            counts[mid] += 1
    return counts.most_common(1)[0][0] if counts else None


def main() -> int:
    assigned, skipped, unresolved = 0, 0, []
    for rep in store.all_reps():
        eid = rep.get("employee_id")
        if not eid:
            continue
        if rep.get("reports_to"):
            skipped += 1
            continue
        manager_id = derive_manager(eid)
        if manager_id is None:
            unresolved.append(eid)
            continue
        store.set_reports_to(eid, manager_id)
        assigned += 1
        print(f"  {eid} {rep.get('name', ''):　<10} → {manager_id}")

    print(f"\nBackfill done: {assigned} assigned, {skipped} already had a manager.")
    if unresolved:
        print(f"Unassigned (no coaching threads): {', '.join(unresolved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
