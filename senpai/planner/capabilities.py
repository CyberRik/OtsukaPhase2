"""The planner's capabilities: one per grounding source, plus the terminal document
producer. Every one is a THIN adapter over logic that already exists — no retrieval,
scoring, or rendering is reimplemented here. This is the whole point of the
capability graph: the planner selects *which* of these run; the engine runs them;
their Evidence lands in one bundle; the Documents capability consumes that bundle.

    conversation ─┐
    workspace ────┤
    crm ──────────┼──►  documents   (depends on all gathered; authors the artifact)
    knowledge ────┤
    web ──────────┘

Gather capabilities emit a uniform `{"text": <grounding>, "label": <section>}` so the
Documents capability can concatenate them into one grounding block regardless of
which were selected. All are READ/SEARCH and degrade to empty — never raise.
"""
from __future__ import annotations

from typing import Any, Mapping

from senpai.orchestration import ExecContext
from senpai.orchestration.evidence import Evidence
from senpai.orchestration.metadata import CapabilityMetadata, OperationKind

# Section-header labels mirror the doc tools' inline grounding blocks, so a deck
# authored via the planner reads identically to one authored via generate_pptx.
_LABELS = {
    "conversation": "これまでの会話・確定済みの文脈",
    "workspace": "ローカル文書（あなたのファイル）",
    "crm": "社内データ",
    "knowledge": "社内ナレッジ",
    "web": "Web検索",
}


def _text_evidence(name: str, text: str, citations=()) -> Evidence:
    text = (text or "").strip()
    if not text:
        return Evidence.empty(provenance={"capability": name})
    return Evidence.ok({"text": text, "label": _LABELS.get(name, name)},
                       citations=tuple(citations), status="ok")


class ConversationCapability:
    """Grounding from the live session — a company/quote/deal already discussed.
    Reuses the doc tools' own `_conversation_grounding` over the published convo."""
    name = "conversation"
    metadata = CapabilityMetadata(OperationKind.READ)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import _conversation_grounding
        text = _conversation_grounding(str(inputs.get("query", "")))
        ctx.emit("会話文脈あり" if text else "会話文脈なし")
        return _text_evidence("conversation", text)


class WorkspaceCapability:
    """Relevant LOCAL documents (sandboxed, read-only). Reuses the doc tools'
    relevance-gated `_workspace_grounding`, which runs the real find→extract."""
    name = "workspace"
    metadata = CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import _workspace_grounding
        text = _workspace_grounding(str(inputs.get("query", "")))
        ctx.emit("該当文書あり" if text else "該当文書なし")
        # Citations are the file provenance already embedded in the text ("出典: file://…").
        return _text_evidence("workspace", text)


class CRMCapability:
    """Internal SPR records for the resolved deal/customer. Reuses `impl.query_spr`."""
    name = "crm"
    metadata = CapabilityMetadata(OperationKind.READ, cacheable=True)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import query_spr
        deal_id = str(inputs.get("deal_id") or "")
        customer_id = str(inputs.get("customer_id") or "")
        if deal_id:
            text, cite = query_spr(deal_id=deal_id), f"SPR {deal_id}"
        elif customer_id:
            text, cite = query_spr(customer=customer_id), f"SPR {customer_id}"
        else:
            return Evidence.empty(provenance={"capability": "crm"})
        ctx.emit("社内記録を取得")
        return _text_evidence("crm", text, citations=[cite])


class KnowledgeCapability:
    """Validated playbook / approved coaching knowledge for the goal. Reuses
    `impl.search_knowledge` (attributed, cited snippets)."""
    name = "knowledge"
    metadata = CapabilityMetadata(OperationKind.SEARCH, cacheable=True)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import search_knowledge
        text = search_knowledge(query=str(inputs.get("query", "")), limit=3)
        if "見つかりません" in text:
            return Evidence.empty(provenance={"capability": "knowledge"})
        ctx.emit("社内ナレッジを取得")
        return _text_evidence("knowledge", text)


class WebCapability:
    """External web search for factual/current topics. Reuses `impl.web_search`."""
    name = "web"
    metadata = CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4, retries=1)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import web_search
        try:
            text = web_search(query=str(inputs.get("query", "")))
        except Exception as e:  # noqa: BLE001 — web is best-effort grounding
            return Evidence.empty(provenance={"capability": "web", "error": str(e)})
        ctx.emit("Web検索を実施")
        return _text_evidence("web", text)


# Order gathered grounding lands in the document, most-specific first.
_GATHER_ORDER = ("conversation", "workspace", "crm", "knowledge", "web")


class DocumentsCapability:
    """The terminal producer: consume the gathered EvidenceBundle (via ctx.deps),
    assemble one grounding block, and author + render + register the artifact —
    reusing the existing author/proposal/render/registry logic. `op` is the doc kind
    (proposal | pptx | docx). This capability does NOT re-gather: its grounding is
    exactly what the selected capabilities put in the bundle."""
    name = "documents"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        kind = op or "pptx"
        if kind == "proposal":
            return self._proposal(inputs, ctx)
        return self._authored(kind, inputs, ctx)

    # -- grounding assembled from the bundle (not re-gathered) -------------------
    def _grounding(self, ctx: ExecContext) -> str:
        by_cap = {ev.capability: ev for ev in ctx.deps.values()}
        blocks = []
        for cap in _GATHER_ORDER:
            ev = by_cap.get(cap)
            if ev and ev.status in ("ok", "partial") and ev.data.get("text"):
                blocks.append(f"【{ev.data.get('label', cap)}】\n{ev.data['text']}")
        return "\n\n".join(blocks)

    def _citations(self, ctx: ExecContext) -> list[str]:
        cites: list[str] = []
        for ev in ctx.deps.values():
            cites.extend(ev.citations)
        return cites

    # -- proposal: deal-scoped, deterministic (GPU-free) ------------------------
    def _proposal(self, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.documents import proposal, registry
        deal_id = str(inputs.get("deal_id") or "")
        if not deal_id:
            return Evidence.error("proposal requires a deal_id",
                                  provenance={"capability": "documents"})
        res = proposal.generate(deal_id, lang=str(inputs.get("lang", "ja")))
        if res is None:
            return Evidence.error(f"deal {deal_id} not found",
                                  provenance={"capability": "documents"})
        path, _pctx, spec = res
        rec = registry.register("proposal", path, deal_id=deal_id)
        ctx.emit(f"提案書を生成: {rec['filename']}")
        return self._artifact_evidence(rec, ctx,
                                       f"提案書(PPTX)を生成しました: {rec['filename']}")

    # -- pptx/docx: free-prompt, authored over the gathered grounding -----------
    def _authored(self, kind: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.documents import author, registry
        from senpai.documents.render import output_path, render_docx, render_pptx
        goal = str(inputs.get("goal") or inputs.get("prompt") or "")
        lang = str(inputs.get("lang", "ja"))
        grounding = self._grounding(ctx)
        if not author._use_llm():
            return Evidence.error("model required for pptx/docx authoring",
                                  provenance={"capability": "documents", "kind": kind})
        if kind == "docx":
            spec = author.author_doc(goal, grounding=grounding, lang=lang)
            if spec is None:
                return Evidence.error("author unavailable",
                                      provenance={"capability": "documents"})
            path = output_path("docx", spec.get("_title") or goal[:30], "docx")
            render_docx(spec, path)
            rec = registry.register("docx", path)
            n = len(spec.get("sections", []))
            msg = f"文書(DOCX)を生成しました: {rec['filename']}（{n}セクション）。"
        else:
            spec = author.author_deck(goal, grounding=grounding, lang=lang)
            if spec is None:
                return Evidence.error("author unavailable",
                                      provenance={"capability": "documents"})
            path = output_path("pptx", spec.get("_title") or goal[:30], "pptx")
            render_pptx(spec, path)
            rec = registry.register("pptx", path)
            n = len(spec.get("slides", []))
            msg = f"プレゼン(PPTX)を生成しました: {rec['filename']}（{n}スライド）。"
        ctx.emit(f"資料を生成: {rec['filename']}")
        return self._artifact_evidence(rec, ctx, msg)

    def _artifact_evidence(self, rec: dict, ctx: ExecContext, msg: str) -> Evidence:
        document = {"doc_id": rec["doc_id"], "kind": rec["kind"],
                    "filename": rec["filename"], "download_url": rec["download_url"]}
        return Evidence.ok(
            {"text": msg, "document": document, "grounded_on": sorted(
                ev.capability for ev in ctx.deps.values()
                if ev.status in ("ok", "partial") and ev.data.get("text"))},
            citations=[*self._citations(ctx), f"doc://{rec['doc_id']}"], status="ok")


# --- workspace WRITE terminals: note (create a text file) + organize (tidy) --------
import re as _re


def _slugify(text: str, default: str = "note") -> str:
    base = _re.sub(r"[^\w]+", "-", (text or "").strip().lower()).strip("-")
    base = _re.sub(r"-{2,}", "-", base)
    return (base[:48] or default)


# Deterministic filename → destination folder classifier for organize. Keyword-based,
# GPU-free; a file that matches nothing lands in "other/". Order = priority.
_ORGANIZE_RULES = (
    ("quotes",        ("見積", "quote", "estimate", "quotation", "お見積")),
    ("proposals",     ("提案", "proposal")),
    ("meeting-notes", ("議事", "meeting", "kickoff", "minutes", "打合", "面談", "notes", "memo", "メモ")),
    ("reports",       ("報告", "report", "レポート")),
    ("contracts",     ("契約", "contract", "nda", "agreement", "覚書")),
)


def _organize_bucket(name: str) -> str:
    low = name.lower()
    for folder, keys in _ORGANIZE_RULES:
        if any(k.lower() in low for k in keys):
            return folder
    return "other"


class WorkspaceWriteCapability:
    """Terminal that WRITES a short text note INTO the workspace (a real file the rep
    keeps), authored from the gathered grounding + the goal. Reuses the existing,
    sandbox-checked, confirm-gated `impl.edit_workspace_document` — this capability
    does not open a path itself. Read-gather → write is how the planner produces a
    persisted note instead of a downloadable artifact."""
    name = "workspace_write"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import edit_workspace_document
        goal = str(inputs.get("goal") or inputs.get("prompt") or "")
        grounding = _grounding_from_deps(ctx)
        content = self._authored(goal, grounding, str(inputs.get("lang", "ja")))
        path = str(inputs.get("path") or "").strip() or self._pick_path(goal)
        result = edit_workspace_document(path, content, confirm=True)
        if result.startswith("エラー") or "エラーが発生" in result:
            return Evidence.error(result, provenance={"capability": "workspace_write"})
        ctx.emit(f"ノートを保存: {path}")
        grounded_on = sorted(ev.capability for ev in ctx.deps.values()
                             if ev.status in ("ok", "partial") and ev.data.get("text"))
        return Evidence.ok({"text": result, "saved_path": path, "kind": "note",
                            "grounded_on": grounded_on},
                           citations=[f"file://{path}"], status="ok")

    def _pick_path(self, goal: str) -> str:
        # A filename named in the goal wins; otherwise a slug under notes/.
        m = _re.search(r"([\w./-]+\.(?:md|txt|json|csv))", goal, _re.IGNORECASE)
        if m:
            return m.group(1)
        return f"notes/{_slugify(goal)}.md"

    def _authored(self, goal: str, grounding: str, lang: str) -> str:
        from senpai.documents import author
        if author._use_llm():
            instr = (
                "You are writing a concise MARKDOWN note to save into the user's files. "
                "Return ONLY the note body (no code fence). "
                f"Write in {'Japanese' if lang == 'ja' else 'English'}.\n"
                f"Use the reference context as the source of facts; do not invent figures.\n"
                f"Request: {goal}\n\n"
                f"{('参考情報:\n' + grounding) if grounding else '(参考情報なし)'}")
            out = author._complete(instr)
            if out:
                return out.strip()
        # Deterministic fallback: the grounding itself, titled.
        title = goal.strip() or "メモ"
        body = grounding or "(参考情報なし)"
        return f"# {title}\n\n{body}\n"


class WorkspaceOrganizeCapability:
    """Terminal that TIDIES the workspace: buckets loose documents into topic folders
    (quotes / proposals / meeting-notes / …) by a deterministic filename classifier.
    `op='plan'` previews the moves (read-only, the default — organizing real files is
    destructive); `op='apply'` performs them via the sandbox's no-overwrite
    `move_within`. Files already inside a subfolder are left alone."""
    name = "workspace_organize"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.workspace import sandbox
        docs = sandbox.list_documents()
        root = sandbox.workspace_root()
        # Only reorganize files sitting at the ROOT (don't churn already-filed docs).
        moves: list[tuple[str, str]] = []
        for p in docs:
            rel = sandbox.rel(p)
            if "/" in rel or "\\" in rel:
                continue  # already in a subfolder
            dest = f"{_organize_bucket(p.name)}/{p.name}"
            if dest != rel:
                moves.append((rel, dest))

        if not moves:
            return Evidence.ok({"text": "整理対象のファイルはありません（すべて分類済み）。",
                                "kind": "organize", "moves": []}, status="ok")

        preview = "\n".join(f"  {s} → {d}" for s, d in moves)
        if op != "apply":
            body = (f"【整理プレビュー（未実行・{len(moves)}件）】\n{preview}\n\n"
                    "実行するには「整理して実行」/「apply」と指示してください。")
            ctx.emit(f"{len(moves)}件の移動を提案")
            return Evidence.ok({"text": body, "kind": "organize", "applied": False,
                                "moves": [{"from": s, "to": d} for s, d in moves]},
                               status="ok")

        done, failed = [], []
        for s, d in moves:
            try:
                sandbox.move_within(s, d)
                done.append((s, d))
            except Exception as e:  # noqa: BLE001 — one bad move must not abort the rest
                failed.append((s, str(e)))
        ctx.emit(f"{len(done)}件を整理")
        lines = [f"【整理を実行しました（{len(done)}件）】",
                 *(f"  {s} → {d}" for s, d in done)]
        if failed:
            lines.append(f"スキップ {len(failed)}件: " + "、".join(f"{s}({e})" for s, e in failed))
        return Evidence.ok({"text": "\n".join(lines), "kind": "organize", "applied": True,
                            "moves": [{"from": s, "to": d} for s, d in done]}, status="ok")


def _grounding_from_deps(ctx: ExecContext) -> str:
    """Assemble gathered grounding from ctx.deps, most-specific-first (shared by the
    Documents and WorkspaceWrite terminals)."""
    by_cap = {ev.capability: ev for ev in ctx.deps.values()}
    blocks = []
    for cap in _GATHER_ORDER:
        ev = by_cap.get(cap)
        if ev and ev.status in ("ok", "partial") and ev.data.get("text"):
            blocks.append(f"【{ev.data.get('label', cap)}】\n{ev.data['text']}")
    return "\n\n".join(blocks)


def build_registry():
    """A registry with all planner capabilities, ready for the ExecutionEngine."""
    from senpai.orchestration import CapabilityRegistry
    reg = CapabilityRegistry()
    for cap in (ConversationCapability(), WorkspaceCapability(), CRMCapability(),
                KnowledgeCapability(), WebCapability(), DocumentsCapability(),
                WorkspaceWriteCapability(), WorkspaceOrganizeCapability()):
        reg.register(cap)
    return reg
