"""The workspace gather plan — one seed `find` task that expands at runtime.

Deliberately tiny: the plan can't know how many documents exist, so it seeds a
single `find` and lets the capability grow the DAG (`ctx.expand`) into N `extract`
tasks once it has looked at the disk. This is the plan whose breadth is decided by
data, not by the author — the whole point of runtime expansion.
"""
from __future__ import annotations

from senpai.orchestration import ExecutionPlan, Task


def workspace_plan(query: str = "", limit: int | None = None) -> ExecutionPlan:
    inputs: dict = {"query": query}
    if limit is not None:
        inputs["limit"] = limit
    return ExecutionPlan(tasks=(
        Task(id="find", capability="workspace", op="find", inputs=inputs,
             group="workspace", summary="関連文書を検索"),
    ))
