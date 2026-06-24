#!/usr/bin/env python3
"""Contract smoke test for the web ↔ engine boundary.

The Next.js app (`web/`) consumes the FastAPI bridge (`senpai/api/server.py`) through
the typed client in `web/lib/api.ts` (shapes declared in `web/lib/types.ts`). When an
engine response changes shape, the UI silently falls back to `web/lib/fixtures.ts` and
the drift goes unnoticed. This script hits each GET endpoint the web client calls and
asserts the top-level keys the TypeScript types expect still exist.

Run it after changing any `/api/*` response (the "endpoint first, then types/api/fixture"
rule — see docs/web-integration.md):

    SENPAI_TODAY=2026-06-16 python scripts/check_contract.py

Uses FastAPI's in-process TestClient, so no server (and no GPU model) is required;
LLM/streaming endpoints degrade gracefully and are intentionally not covered here.
Exits non-zero on the first contract mismatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the repo root importable when run as `python scripts/check_contract.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import senpai.api.server as server
from senpai.data import store

client = TestClient(server.app)

# Representative ids pulled live from the store so path endpoints stay valid.
_rep = store.all_reps()[0]["employee_id"]
_customer = store.all_customers()[0]["customer_id"]
_deal = store.all_deals()[0]["deal_id"]

# endpoint -> set of top-level keys web/lib/api.ts + types.ts rely on.
CHECKS: list[tuple[str, set[str]]] = [
    ("/api/health", {"status"}),
    ("/api/dashboard", {"kpis", "deals", "flags"}),
    (f"/api/deals/{_deal}", {"deal", "score", "band"}),
    ("/api/coaching", {"needs_coaching", "trends", "confidence", "summary"}),
    ("/api/coach/rep-profiles", {"reps"}),
    (f"/api/coach/rep-profile/{_rep}", {"employee_id", "weaknesses", "strengths", "talking_points", "threads"}),
    (f"/api/coach/rep-progress/{_rep}", {"employee_id", "windows", "series", "trends", "headline"}),
    ("/api/coach/threads", {"threads"}),
    ("/api/coach/examples", {"examples"}),
    ("/api/growth", {"growth"}),
    ("/api/knowledge/principles", {"principles"}),
    ("/api/knowledge/items", {"items"}),
    ("/api/knowledge/sources", {"sources"}),
    (f"/api/account/{_customer}", {"customer_id", "customer", "health", "active_deals", "recommended_focus"}),
]


def main() -> int:
    failures: list[str] = []
    for path, expected in CHECKS:
        try:
            res = client.get(path)
        except Exception as exc:  # noqa: BLE001 — report, don't crash the whole run
            failures.append(f"{path}: request raised {exc!r}")
            continue
        if res.status_code != 200:
            failures.append(f"{path}: HTTP {res.status_code}")
            continue
        body = res.json()
        if not isinstance(body, dict):
            failures.append(f"{path}: expected a JSON object, got {type(body).__name__}")
            continue
        missing = expected - body.keys()
        if missing:
            failures.append(f"{path}: missing keys {sorted(missing)} (got {sorted(body.keys())})")
        else:
            print(f"  ok  {path}")

    if failures:
        print("\nCONTRACT DRIFT — the web client expects keys the bridge no longer returns:")
        for f in failures:
            print(f"  ✗ {f}")
        print("\nFix server.py to restore the shape, or update web/lib/{types,api,fixtures}.ts to match.")
        return 1

    print(f"\nAll {len(CHECKS)} web-consumed endpoints match the expected contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
