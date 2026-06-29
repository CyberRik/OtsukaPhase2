"""Extension seam: the Planner interface.

M0/M1 build plans with plain functions (e.g. a future `research_plan(target)`
returning an `ExecutionPlan`) — there is deliberately no Planner object yet. This
Protocol exists so that when open-ended intents need it, a `TemplatePlanner`
(deterministic named seeds) and later an `LLMPlanner` (picks capabilities for a
free-text request) can drop in without changing the engine or routes: both just
produce an `ExecutionPlan`.

The Planner decides *what capabilities run and in what order* — never reasoning.
"""
from __future__ import annotations

from typing import Any, Protocol

from senpai.orchestration.capability import ExecutionPlan


class Planner(Protocol):
    def plan(self, intent: str, target: Any) -> ExecutionPlan:
        ...
