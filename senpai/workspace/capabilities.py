"""The Workspace capability: `find` (discover relevant documents) and `extract`
(read one document to text). Both are deterministic and READ-ONLY.

Runtime DAG expansion lives here — this is the first production user of `ctx.expand`:
a single `find` task selects the relevant documents and then *appends one `extract`
task per document*, which the engine runs in parallel. The breadth of a real query
("everything about Endo Kogyo") is unknowable at plan time, so the plan seeds one
`find` and grows to fit what's actually on disk.

    workspace:find ──► ctx.expand ──► workspace:extract × N   (parallel)

Every fragment lands in the same EvidenceBundle as CRM/Knowledge/Web evidence, so a
future LLMPlanner can orchestrate local files alongside the seed DB.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from senpai import config
from senpai.orchestration import ExecContext
from senpai.orchestration.capability import Task
from senpai.orchestration.evidence import Evidence
from senpai.workspace import sandbox
from senpai.workspace.extract import extract_text

_TOKEN_RE = re.compile(r"[0-9A-Za-z]+|[぀-ヿ一-鿿]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _score(query: str, path: Path) -> float:
    """Relevance of a file to the query, from its name + relative path only (cheap,
    no read). Latin tokens match as words; CJK runs match as substrings. Empty query
    → 0 for everyone, so the caller falls back to recency."""
    hay = f"{sandbox.rel(path)} {path.name}".lower()
    score = 0.0
    for tok in _tokens(query):
        if tok in hay:
            # Whole-name hits and longer tokens are worth more than incidental ones.
            score += 2.0 if tok in path.stem.lower() else 1.0
            score += min(len(tok), 6) * 0.1
    return score


def _meta(path: Path, score: float) -> dict:
    st = path.stat()
    return {"path": str(path), "rel": sandbox.rel(path), "name": path.name,
            "ext": path.suffix.lower(), "size": st.st_size, "mtime": st.st_mtime,
            "score": round(score, 2)}


class WorkspaceCapability:
    """Sandboxed local documents. `find` discovers + fans out; `extract` reads one."""
    name = "workspace"

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        if op == "extract":
            return self._extract(inputs, ctx)
        return self._find(inputs, ctx)

    # -- find: select relevant docs, then expand into one extract task each --------
    def _find(self, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        query = str(inputs.get("query", "") or "")
        limit = int(inputs.get("limit", config.WORKSPACE_MAX_FILES))
        limit = max(1, min(limit, config.WORKSPACE_MAX_FILES))

        docs = sandbox.list_documents()
        if not docs:
            ctx.emit("no documents in workspace")
            return Evidence.empty(provenance={"root": str(sandbox.workspace_root()),
                                              "available": 0})

        scored = [(_score(query, p), p) for p in docs]
        any_match = any(s > 0 for s, _ in scored)
        if any_match:
            scored = [(s, p) for s, p in scored if s > 0]
            scored.sort(key=lambda sp: (sp[0], sp[1].stat().st_mtime), reverse=True)
        else:
            # No query signal (or nothing matched) → most-recently-modified first.
            scored.sort(key=lambda sp: sp[1].stat().st_mtime, reverse=True)
        chosen = [p for _s, p in scored[:limit]]
        files = [_meta(p, s) for s, p in scored[:limit]]

        # Runtime fan-out: one extract task per chosen document, run in parallel.
        ctx.expand([
            Task(id=f"{ctx.task_id}:extract:{i}", capability="workspace", op="extract",
                 inputs={"path": m["path"], "rel": m["rel"], "name": m["name"]},
                 group="workspace", summary=f"読み込み: {m['name']}")
            for i, m in enumerate(files)
        ])
        ctx.emit(f"{len(files)} 件の文書を抽出 (全{len(docs)}件中)")
        return Evidence.ok(
            {"files": files, "count": len(files), "available": len(docs),
             "matched": any_match, "query": query},
            citations=[f"file://{m['rel']}" for m in files],
            status="ok",
            provenance={"root": str(sandbox.workspace_root()), "op": "find"})

    # -- extract: read one document to text -------------------------------------
    def _extract(self, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        raw_path = str(inputs.get("path", "") or "")
        try:
            path = sandbox.safe_path(raw_path)
        except sandbox.SandboxError as e:
            return Evidence.error(str(e), provenance={"path": raw_path})
        if not sandbox.is_allowed(path):
            return Evidence.error("file not found or not allowed",
                                  provenance={"path": raw_path})
        rel = inputs.get("rel") or sandbox.rel(path)
        res = extract_text(path)
        ctx.emit(f"{path.name}: {res['chars']}字")
        data = {"name": inputs.get("name") or path.name, "rel": rel,
                "ext": res["ext"], "text": res["text"], "chars": res["chars"],
                "truncated": res["truncated"]}
        if res.get("error") and not res["text"]:
            data["error"] = res["error"]
            return Evidence.ok(data, citations=[f"file://{rel}"], status="empty",
                               confidence=0.0, provenance={"path": str(path)})
        return Evidence.ok(data, citations=[f"file://{rel}"],
                           confidence=1.0 if res["text"] else 0.0,
                           status="ok" if res["text"] else "empty",
                           provenance={"path": str(path)})


def build_registry():
    from senpai.orchestration import CapabilityRegistry
    reg = CapabilityRegistry()
    reg.register(WorkspaceCapability())
    return reg
