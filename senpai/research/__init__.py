"""Research workflow on the orchestration spine (M1).

Thin capabilities that wrap the existing deterministic store/scoring logic, a
`research_plan()` that wires them into a dependency graph, and a gather function
that runs the engine and assembles the result into the SAME structure the legacy
`_build_research_bundle` / `_build_deal_context_bundle` produced — so `/research`
behaves identically while running on the new engine.

No business logic is reinvented here: every capability calls the same `store`,
`score_deal`, `find_similar_deals`, and `web_search_typed` the route used before.
"""
from __future__ import annotations

from senpai.research.capabilities import build_registry
from senpai.research.gather import research_bundle_fields, web_search_via_engine
from senpai.research.plan import research_plan, web_plan

__all__ = [
    "build_registry",
    "research_plan",
    "web_plan",
    "research_bundle_fields",
    "web_search_via_engine",
]