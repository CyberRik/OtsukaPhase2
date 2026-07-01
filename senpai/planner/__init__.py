"""LLMPlanner spine — translate a user goal into a capability graph and run it.

Minimal by design (milestone 1: document generation). The planner selects *which*
capabilities are needed to ground a document; the existing ExecutionEngine runs the
resulting plan; the EvidenceBundle feeds the terminal Documents capability. It is
not autonomous and not recursive — one selection, one static plan, one execution.

    goal ──► LLMPlanner ──► ExecutionPlan ──► ExecutionEngine ──► EvidenceBundle ──► artifact

Public surface:
    LLMPlanner         — .plan(goal) / .select(goal) → ExecutionPlan / Selection
    document_plan      — Selection → ExecutionPlan (the fixed 2-level DAG)
    run_document_goal  — plan → execute → artifact, end to end
    build_registry     — the planner's capability registry for the engine
"""
from __future__ import annotations

from senpai.planner.capabilities import build_registry
from senpai.planner.llm_planner import LLMPlanner
from senpai.planner.plan import document_plan
from senpai.planner.run import run_document_goal
from senpai.planner.selection import Selection, heuristic_selection

__all__ = [
    "LLMPlanner",
    "Selection",
    "heuristic_selection",
    "document_plan",
    "run_document_goal",
    "build_registry",
]
