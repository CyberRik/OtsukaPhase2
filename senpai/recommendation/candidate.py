"""`Candidate` — one item any domain's generator proposes, before ranking or
explanation. Deliberately thin and domain-agnostic: a solution, an action, a
playbook entry, a document template, or an expert to route to are all just a
`kind` + a stable `id` + a `match_score` + why it was proposed. Domain-specific
detail (a solution's category/summary/source URL, say) lives in `payload` —
`ranking.py` never needs to know what's in there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Candidate:
    kind: str                          # "solution" | future: "action"/"playbook"/"document"/"expert"
    id: str                            # stable, real identifier (a URL, a record id) — never invented
    title: str
    match_score: float                 # deterministic — this layer's own score, not an LLM's confidence
    reasons: tuple[str, ...] = ()       # machine-readable, e.g. "category_match", "expansion:cross_sell:サーバー"
    evidence: tuple[str, ...] = ()      # citation handles — same convention as orchestration.evidence.Evidence
    payload: Mapping[str, Any] = field(default_factory=dict)  # domain-specific extra fields
