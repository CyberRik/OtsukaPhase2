"""Run an agent's gather plan on the engine and adapt engine events back to the
legacy crew `agent_tool` events, so the Workspace timeline is byte-for-byte the same.

`run_agent_gather` returns {task_id: tool_string} for the agent to assemble its
grounding exactly as before. A failed/degraded task yields "" for its slot (the
engine never crashes the gather), where the old inline code would have raised.
"""
from __future__ import annotations

from typing import Callable

from senpai.agent.capabilities import build_registry
from senpai.orchestration import ExecutionEngine, ExecutionPlan
from senpai.orchestration import events as oevents

_REGISTRY = build_registry()
Emit = Callable[[dict], None]


def run_agent_gather(plan: ExecutionPlan, agent_id: str, emit: Emit) -> dict[str, str]:
    """Execute `plan` on the engine. Each task.started becomes the agent's legacy
    `agent_tool` event (same name/summary/order); other engine events are internal.
    Returns the tools' string outputs keyed by task id."""
    def adapter(ev: dict) -> None:
        if ev["type"] == oevents.TASK_STARTED:
            emit({"type": "agent_tool", "agent_id": agent_id,
                  "name": ev["op"] or ev["capability"], "summary": ev["summary"]})

    bundle = ExecutionEngine(_REGISTRY).run(plan, adapter)
    out: dict[str, str] = {}
    for task in plan.tasks:
        ev = bundle.get(task.id)
        out[task.id] = (ev.data.get("text", "") if ev and ev.status != "error" else "")
    return out
