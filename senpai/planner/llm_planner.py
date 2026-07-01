"""LLMPlanner — translate a user goal into a capability graph. Nothing more.

This is intentionally NOT an autonomous or recursive agent. It makes exactly ONE
decision — *which capabilities are needed to ground this document* — and emits a
static `ExecutionPlan`. The Execution Engine runs it; the capabilities do the work;
the bundle feeds the artifact. The planner never executes, never loops, never
reasons over results.

    goal ──► LLMPlanner.plan() ──► ExecutionPlan ──► ExecutionEngine ──► EvidenceBundle

The LLM picks the capability SET (and the document kind). It is deliberately NOT
trusted with IDs, ordering, or execution: the entity a document grounds in is
resolved deterministically from the store (selection.py), the edges are fixed
(plan.py), and any model failure falls straight back to the deterministic
`heuristic_selection`. So the planner is useful with a model and correct without one.
"""
from __future__ import annotations

import json
from typing import Any

from senpai.orchestration.capability import ExecutionPlan
from senpai.planner.plan import document_plan
from senpai.planner.selection import (
    GATHER_CAPABILITIES,
    Selection,
    ground_selection,
    heuristic_selection,
)

_CAP_DESC = (
    "conversation: この会話ですでに確定した文脈（前ターンで読んだ会社・見積・案件）。ほぼ常に有用。\n"
    "workspace: 手元のローカル文書（PDF/DOCX/PPTX/XLSX/TXT/MD）。社名や案件がファイルにある時。\n"
    "crm: 社内SPRの顧客・案件記録。対象がCRMに存在する時。\n"
    "knowledge: 承認済みの営業ナレッジ・プレイブック。提案の論拠付けに。\n"
    "web: 外部の事実・最新情報・市場価格など、社外の一般トピックの時のみ。"
)


class LLMPlanner:
    """Selects gathering capabilities for a document goal, then builds the plan.

    `plan(goal, ...)` is the whole surface. Implements the `Planner` protocol
    (`plan(intent, target)`), plus keyword context (`conversation`, `role`) the
    document flow uses. Returns an `ExecutionPlan` — the engine takes it from there.
    """

    def plan(self, intent: str, target: Any = None, *,
             conversation: list[dict] | None = None, role: str = "junior",
             deal_id: str | None = None) -> ExecutionPlan:
        return document_plan(self.select(intent, conversation=conversation,
                                         deal_id=deal_id))

    # -- capability selection (the one decision) --------------------------------
    def select(self, goal: str, *, conversation: list[dict] | None = None,
               deal_id: str | None = None) -> Selection:
        base = heuristic_selection(goal, deal_hint=deal_id)   # deterministic + ID grounding
        # Workspace ops (organize / note) are clear from the phrasing — the LLM's
        # capability-selection is only for document GENERATION, so keep these
        # deterministic and skip the extra round-trip.
        if base.doc_kind in ("organize", "note"):
            return base
        from senpai.documents.author import _use_llm
        if not _use_llm():
            return base
        chosen = self._llm_select(goal, conversation)
        if chosen is None:
            return base
        caps, doc_kind = chosen
        return ground_selection(goal, caps, doc_kind, reason="llm-selected",
                                deal_hint=deal_id)

    def _llm_select(self, goal: str, conversation) -> tuple[list[str], str] | None:
        """Ask the model which capabilities to gather + the doc kind. Strict JSON;
        returns None on any failure so the caller keeps the heuristic selection."""
        convo_hint = _recent_context(conversation)
        prompt = (
            "あなたは営業支援システムの『資料生成プランナー』です。ユーザーの目標を達成する"
            "ために、どの情報源(capability)を集めるべきかだけを選びます。実行や推論はしません。\n\n"
            "利用可能な capability:\n" + _CAP_DESC + "\n\n"
            "厳密なJSONのみを返すこと（前置き・コードフェンス禁止）:\n"
            '{"capabilities": ["conversation", ...], "doc_kind": "proposal|pptx|docx", '
            '"reason": "..."}\n'
            "doc_kind: 特定の案件/顧客への提案なら proposal、一般スライドは pptx、文書は docx。\n"
            "conversation は常に含めること。外部の一般トピックでない限り web は含めない。\n\n"
            + (f"これまでの会話の要点:\n{convo_hint}\n\n" if convo_hint else "")
            + f"ユーザーの目標: {goal}"
        )
        try:
            from senpai.llm.client import simple_complete
            raw = simple_complete([{"role": "user", "content": prompt}],
                                  temperature=0.0, max_tokens=300,
                                  no_think=True, allow_fallback=False)
        except Exception:  # noqa: BLE001 — model down/timeout → heuristic
            return None
        obj = _extract_json(raw)
        if not isinstance(obj, dict):
            return None
        caps = obj.get("capabilities")
        doc_kind = obj.get("doc_kind")
        if not isinstance(caps, list) or not isinstance(doc_kind, str):
            return None
        caps = [c for c in caps if c in set(GATHER_CAPABILITIES)]
        return caps, doc_kind


def _recent_context(conversation) -> str:
    """A short tail of the conversation for the selector prompt (roles + trimmed text)."""
    if not conversation:
        return ""
    lines = []
    for m in conversation[-6:]:
        role, content = m.get("role"), m.get("content")
        if role == "system" or not isinstance(content, str) or not content.strip():
            continue
        lines.append(f"[{role}] {content.strip()[:200]}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    import re
    t = re.sub(r"```(?:json)?", "", text).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
