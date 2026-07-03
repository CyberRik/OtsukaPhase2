"""Run a document goal end-to-end through the planner spine:

    goal ──► LLMPlanner ──► ExecutionPlan ──► ExecutionEngine ──► EvidenceBundle ──► artifact

`run_document_goal` is the one entry point. It plans, publishes the conversation so
the Conversation/Documents capabilities can see it, executes the plan on the shared
ExecutionEngine, and reads the terminal `documents` fragment out of the bundle as
the artifact. Gather failures degrade to empty (the engine never crashes a run), so
a down web search or an empty workspace just means less grounding — never no deck.

For document generation the "Reasoner" step is trivial — the artifact IS the file,
and the Documents capability already produced the one-line confirmation. The Reasoner
seam (senpai/orchestration/reason.py) is where meeting-prep / account-intelligence
will synthesize prose over the bundle in the next milestone.

`python -m senpai.planner.run "D001 の提案書を作って"` runs it (proposal path is GPU-free).
"""
from __future__ import annotations

from typing import Callable

from senpai.orchestration import EvidenceBundle, ExecutionEngine
from senpai.planner.capabilities import build_registry
from senpai.planner.llm_planner import LLMPlanner

Emit = Callable[[dict], None]
_NOOP: Emit = lambda _ev: None


def run_document_goal(goal: str, *, conversation: list[dict] | None = None,
                      role: str = "junior", deal_id: str | None = None,
                      registry=None, emit: Emit | None = None) -> dict:
    """Plan → execute → artifact for a document-generation goal. Returns:
      {goal, plan: [{id, capability, op, depends_on}], selection, document, text,
       grounded_on, citations, capabilities}
    `document` is None if authoring needed a model that was unavailable (then `text`
    carries the reason). Publishes `conversation` for the grounding capabilities.
    `deal_id` (e.g. the deal picked in the selector) is authoritative when given."""
    if conversation is not None:
        from senpai.tools import conversation as _conv
        _conv.set_conversation(conversation)

    planner = LLMPlanner()
    selection = planner.select(goal, conversation=conversation, deal_id=deal_id)
    plan = __import__("senpai.planner.plan", fromlist=["document_plan"]).document_plan(selection)

    bundle: EvidenceBundle = ExecutionEngine(registry or build_registry()).run(
        plan, emit or _NOOP)

    # The terminal task is the one nothing else depends on (documents / workspace_write
    # / workspace_organize) — read its fragment as the artifact, whatever the kind.
    depended = {d for t in plan.tasks for d in t.depends_on}
    terminal = next((t for t in reversed(plan.tasks) if t.id not in depended), None)
    doc = bundle.get(terminal.id) if terminal else None
    document = None
    text = ""
    grounded_on: list[str] = []
    outline: list = []
    if doc is not None and doc.status in ("ok", "partial"):
        document = doc.data.get("document")
        text = doc.data.get("text", "")
        grounded_on = list(doc.data.get("grounded_on", []))
        outline = list(doc.data.get("outline", []))
    elif doc is not None:  # error fragment
        text = str(doc.provenance.get("error", "document generation failed"))

    return {
        "goal": goal,
        "selection": {"doc_kind": selection.doc_kind, "deal_id": selection.deal_id,
                      "customer_id": selection.customer_id, "target": selection.target,
                      "capabilities": list(selection.capabilities),
                      "reason": selection.reason},
        "plan": [{"id": t.id, "capability": t.capability, "op": t.op,
                  "depends_on": sorted(t.depends_on)} for t in plan.tasks],
        "capabilities": list(selection.capabilities),
        "document": document,
        "text": text,
        "grounded_on": grounded_on,
        "outline": outline,
        "citations": list(doc.citations) if doc else [],
    }


if __name__ == "__main__":
    import json
    import sys

    goal = " ".join(sys.argv[1:]) or "D001 の提案書を作成して"
    result = run_document_goal(goal, emit=lambda ev: None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
