"""Run the workspace plan on the engine and reduce it to grounded evidence.

`workspace_evidence` returns the structured result (found files + extracted docs +
citations) straight from the EvidenceBundle — the shape a future LLMPlanner consumes
alongside CRM/Knowledge/Web evidence. `gather_workspace_documents` reduces that to
one compact grounded string for the chat loop, exactly like `segment_intelligence`:
the tool returns retrieval, the chat loop's synthesis round does the "reduce".
"""
from __future__ import annotations

from typing import Callable

from senpai.orchestration import EvidenceBundle, ExecutionEngine
from senpai.workspace.capabilities import build_registry
from senpai.workspace.plan import workspace_plan

Emit = Callable[[dict], None]
_NOOP: Emit = lambda _ev: None


def workspace_evidence(query: str = "", *, limit: int | None = None,
                       registry=None, emit: Emit | None = None) -> dict:
    """Gather local documents for `query` on the engine (find → fan-out extract×N).
    Returns {root, available, query, found: [file meta], documents: [{name, rel,
    ext, text, chars, truncated}], citations}. Degrades to an empty result when the
    workspace is missing/empty — never raises."""
    plan = workspace_plan(query, limit=limit)
    bundle: EvidenceBundle = ExecutionEngine(registry or build_registry()).run(
        plan, emit or _NOOP)

    find = bundle.get("find")
    found = list(find.data.get("files", [])) if find else []
    root = (find.provenance.get("root") if find else "") or ""
    available = (find.data.get("available", 0) if find else 0)

    documents = []
    # Extract fragments are the runtime-expanded tasks keyed "find:extract:<i>".
    for task_id, ev in bundle.fragments.items():
        if not task_id.startswith("find:extract:"):
            continue
        if ev.status == "error" or not ev.data.get("text"):
            continue
        documents.append({k: ev.data.get(k) for k in
                          ("name", "rel", "ext", "text", "chars", "truncated")})
    documents.sort(key=lambda d: d["rel"])
    # Did the query actually match any filename, or did `find` fall back to recency?
    # Surfacing this lets the chat loop tell the model "nothing matched — these are
    # just the most recent files", so it answers instead of rephrasing endlessly.
    matched = bool(find.data.get("matched")) if find else False
    return {
        "root": root, "available": available, "query": query, "matched": matched,
        "found": found, "documents": documents,
        "citations": [f"file://{d['rel']}" for d in documents],
    }


def _format(res: dict) -> str:
    """Compact grounded string for the chat loop (the 'map'; the loop does 'reduce')."""
    docs = res["documents"]
    if not docs:
        if not res["available"]:
            return "ワークスペースに参照可能な文書がありません。"
        return f"「{res['query']}」に関連する文書は見つかりませんでした（全{res['available']}件）。"
    q = str(res.get("query", "")).strip()
    if q and not res.get("matched"):
        # No filename matched — `find` fell back to most-recent. Tell the model plainly
        # so it stops rephrasing (filename-only search → synonyms give the SAME set)
        # and answers from what's here (or says the info isn't in the files).
        header = (f"注: 「{q}」に一致するファイル名はありませんでした。ファイル名検索のため、"
                  f"別の言葉で再検索しても結果は同じです。代わりに最近の文書 {len(docs)}件"
                  f"（全{res['available']}件中）を表示します。関連情報がなければ、その旨を述べてください:")
    else:
        header = f"ワークスペース文書 {len(docs)}件（全{res['available']}件中）:"
    blocks = []
    for d in docs:
        trunc = "（一部）" if d.get("truncated") else ""
        blocks.append(f"■ {d['name']}{trunc}\n{d['text']}\n出典: file://{d['rel']}")
    return header + "\n\n" + "\n\n".join(blocks)


def gather_workspace_documents(query: str = "", *, limit: int | None = None) -> str:
    """The chat-tool entry point: grounded string with per-document file citations."""
    return _format(workspace_evidence(query, limit=limit))
