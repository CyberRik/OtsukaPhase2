"""`document_plan(selection)` — turn a capability Selection into an ExecutionPlan.

The graph is deliberately shallow (two levels), which is all document generation
needs and keeps the first planner minimal:

    Level 0 (parallel gather):  conversation / workspace / crm / knowledge / web
    Level 1 (terminal):         documents  ── depends on every gather task

Every gather task runs in parallel (they're independent READ/SEARCH); the single
`documents` task depends on all of them, so the engine runs it only after the
grounding is in the bundle. The edges ARE the dependency: no ordering logic lives
in the engine or the capabilities — it's entirely expressed by `depends_on`.
"""
from __future__ import annotations

from senpai.orchestration import ExecutionPlan, Task, TaskPolicy
from senpai.planner.selection import Selection

_GATHER = "gather"
_DOCS = "documents"


def document_plan(sel: Selection) -> ExecutionPlan:
    query = sel.goal

    # Organize is a self-contained WRITE over the workspace — no gather graph.
    if sel.doc_kind == "organize":
        return ExecutionPlan(tasks=(Task(
            id="workspace_organize", capability="workspace_organize",
            op="apply" if sel.confirm else "plan", inputs={"confirm": sel.confirm},
            policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary="ワークスペースを整理"),))

    gather: list[Task] = []

    if "conversation" in sel.capabilities:
        gather.append(Task(id="conversation", capability="conversation",
                           inputs={"query": query}, group=_GATHER,
                           summary="会話の文脈を収集"))
    if "workspace" in sel.capabilities:
        gather.append(Task(id="workspace", capability="workspace",
                           inputs={"query": query}, group=_GATHER,
                           summary="ローカル文書を検索・抽出"))
    if "crm" in sel.capabilities:
        gather.append(Task(id="crm", capability="crm",
                           inputs={"deal_id": sel.deal_id or "",
                                   "customer_id": sel.customer_id or ""},
                           group=_GATHER, summary="社内記録を取得"))
    if "knowledge" in sel.capabilities:
        gather.append(Task(id="knowledge", capability="knowledge",
                           inputs={"query": query}, group=_GATHER,
                           summary="社内ナレッジを照合"))
    if "web" in sel.capabilities:
        gather.append(Task(id="web", capability="web",
                           inputs={"query": query}, group=_GATHER,
                           summary="Web検索でカバー"))

    deps = frozenset(t.id for t in gather)
    # A note WRITEs into the workspace; proposal/pptx/docx GENERATE a downloadable file.
    if sel.doc_kind == "note":
        terminal = Task(
            id="workspace_write", capability="workspace_write", op="note",
            inputs={"goal": query, "prompt": query, "path": sel.path, "lang": sel.lang},
            depends_on=deps, policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary="ノートを保存")
    else:
        # "cover all of this customer's deals" (proposal only) — the deterministic
        # generator merges every deal on file instead of silently grounding on
        # just the biggest one.
        deal_ids: list[str] = []
        if sel.doc_kind == "proposal" and sel.all_deals and sel.customer_id:
            from senpai.data import store as _store
            deal_ids = [d["deal_id"] for d in _store.deals_for_customer(sel.customer_id)]

        terminal = Task(
            id="documents", capability="documents", op=sel.doc_kind,
            inputs={"goal": query, "prompt": query, "deal_id": sel.deal_id or "",
                    "customer_id": sel.customer_id or "", "deal_ids": deal_ids,
                    "target": sel.target, "lang": sel.lang, "title": sel.title},
            depends_on=deps,
            # A WRITE deliverable: never auto-repeat, run after the grounding is in.
            policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary=f"{sel.doc_kind} を生成")

    return ExecutionPlan(tasks=(*gather, terminal))
