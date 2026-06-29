"""account_plan() — the account-commentary gather as an engine plan.

A single deterministic gather task (the account context package). Kept as its own
plan so the route reads like the other migrated workflows and so the package can be
decomposed into parallel sub-gathers later without changing the route.
"""
from __future__ import annotations

from senpai.orchestration import ExecutionPlan, Task


def account_plan(customer_id: str, lang: str = "ja", today=None) -> ExecutionPlan:
    return ExecutionPlan(tasks=(
        Task(id="account_context", capability="account_context",
             inputs={"customer_id": customer_id, "lang": lang, "today": today},
             group="account", summary="アカウント全体の状況を集約"),
    ))
