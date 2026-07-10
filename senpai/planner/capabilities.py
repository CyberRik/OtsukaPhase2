"""The planner's capabilities: one per grounding source, plus the terminal document
producer. Every one is a THIN adapter over logic that already exists — no retrieval,
scoring, or rendering is reimplemented here. This is the whole point of the
capability graph: the planner selects *which* of these run; the engine runs them;
their Evidence lands in one bundle; the Documents capability consumes that bundle.

    conversation ─┐
    workspace ────┤
    crm ──────────┼──►  documents   (depends on all gathered; authors the artifact)
    knowledge ────┤
    solutions ────┤
    web ──────────┘

Gather capabilities emit a uniform `{"text": <grounding>, "label": <section>}` so the
Documents capability can concatenate them into one grounding block regardless of
which were selected. All are READ/SEARCH and degrade to empty — never raise.
"""
from __future__ import annotations

import re
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
    "solutions": "大塚商会ソリューション・製品情報",
    "web": "Web検索",
}


# workspace/knowledge/solutions already embed real provenance inline
# ("出典: file://…", "出典: Playbook 123", "根拠: 先輩2名 / int001") but only CRM
# passes an explicit `citations` list — without this, the evidence-count receipt
# line always read 0 for them even when real grounding was retrieved.
_CITATION_RE = re.compile(r"(?:出典|根拠):\s*([^\n）)]+)")


def _extract_citations(text: str) -> list[str]:
    return [m.strip() for m in _CITATION_RE.findall(text)]


def _text_evidence(name: str, text: str, citations=()) -> Evidence:
    text = (text or "").strip()
    if not text:
        return Evidence.empty(provenance={"capability": name})
    citations = tuple(citations) or tuple(_extract_citations(text))
    return Evidence.ok({"text": text, "label": _LABELS.get(name, name)},
                       citations=citations, status="ok")


def _register_deck(registry, files: dict, *, primary_kind: str,
                   deal_id: str | None = None) -> list[dict]:
    """Register a deck's export set (from export.render_deck) for download — the editable
    office file first (primary), then PDF, then source HTML — and return the records, with
    the primary at index 0. Mirrors impl._register_deck_files for the planner path."""
    recs = [registry.register(primary_kind, files["pptx"], deal_id=deal_id)]
    if files.get("pdf"):
        recs.append(registry.register("pdf", files["pdf"], deal_id=deal_id))
    if files.get("html"):
        recs.append(registry.register("html", files["html"], deal_id=deal_id))
    return recs


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
        from senpai.data import store
        from senpai.tools.impl import query_spr
        deal_id = str(inputs.get("deal_id") or "")
        customer_id = str(inputs.get("customer_id") or "")
        if deal_id:
            text, cite = query_spr(deal_id=deal_id), f"SPR {deal_id}"
        elif customer_id:
            text, cite = query_spr(customer=customer_id), f"SPR {customer_id}"
            # query_spr's customer branch is a summary line per deal only — unlike
            # its deal_id branch, it never includes activity/daily-report history.
            # Without an open deal_id (the common case for a closed-won/lost
            # account), that history is the only place a real win/loss reason
            # ("competitor comparison", "budget on hold") lives — pull it directly
            # so authoring doesn't have to guess a cause.
            acts = store.activities_for_customer(customer_id)[:5]
            if acts:
                text += "\n直近の活動:\n" + "\n".join(
                    f"  ・{a['activity_date']} {a['deal_id']} [{a['activity_type']}] {a['daily_report']}"
                    for a in acts)
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
        from senpai.tools.outcomes import is_miss
        text = search_knowledge(query=str(inputs.get("query", "")), limit=3)
        if is_miss(text):
            return Evidence.empty(provenance={"capability": "knowledge"})
        ctx.emit("社内ナレッジを取得")
        return _text_evidence("knowledge", text)


class SolutionsCapability:
    """Real Otsuka Shokai product/solution pages for the goal — named products/
    services to ground a pitch, not just an internal category label. Reuses
    `impl.search_solutions` (attributed, cited snippets).

    The raw goal text is usually an imperative ("make a proposal for D001"), not
    a description of the customer's need — a bad query for the product corpus.
    When a deal/customer resolved, its product_category/industry describe the
    actual need and are folded into the query; the raw goal is kept too so a
    free-form ask ("...for a paperless office push") still contributes signal."""
    name = "solutions"
    metadata = CapabilityMetadata(OperationKind.SEARCH, cacheable=True)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.data import store
        from senpai.tools.impl import search_solutions

        goal = str(inputs.get("query", ""))
        deal_id = str(inputs.get("deal_id") or "")
        customer_id = str(inputs.get("customer_id") or "")
        deal = store.get_deal(deal_id) if deal_id else None
        category = (deal or {}).get("product_category", "")
        if not customer_id and deal:
            customer_id = deal.get("customer_id", "")
        customer = store.get_customer(customer_id) if customer_id else None
        industry = (customer or {}).get("industry", "")

        query = " ".join(p for p in (category, industry, goal) if p)
        if not query:
            return Evidence.empty(provenance={"capability": "solutions"})

        from senpai.tools.outcomes import is_miss
        text = search_solutions(query=query, limit=3)
        if is_miss(text):
            return Evidence.empty(provenance={"capability": "solutions"})
        ctx.emit("ソリューション・製品情報を取得")
        return _text_evidence("solutions", text)


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
_GATHER_ORDER = ("conversation", "workspace", "crm", "knowledge", "solutions", "web")


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
        deal_ids = [str(d) for d in (inputs.get("deal_ids") or [])]
        res = proposal.generate(deal_id, lang=str(inputs.get("lang", "ja")),
                                deal_ids=deal_ids or None)
        if res is None:
            return Evidence.error(f"deal {deal_id} not found",
                                  provenance={"capability": "documents"})
        files, doc_ctx, spec = res
        recs = _register_deck(registry, files, primary_kind="proposal", deal_id=deal_id)
        rec = recs[0]
        ctx.emit(f"提案書を生成: {rec['filename']}")
        outline = [{"title": s.get("title", "")} for s in spec.get("slides", [])]
        n = len(doc_ctx.deals)
        msg = (f"提案書(PPTX)を生成しました: {rec['filename']}（{n}件の案件を統合）"
              if n > 1 else f"提案書(PPTX)を生成しました: {rec['filename']}")
        return self._artifact_evidence(rec, ctx, msg, outline=outline, recs=recs)

    # -- pptx/docx: free-prompt, authored over the gathered grounding -----------
    def _authored(self, kind: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.documents import author, registry
        from senpai.documents.render import output_path, render_docx
        goal = str(inputs.get("goal") or inputs.get("prompt") or "")
        lang = str(inputs.get("lang", "ja"))
        # Whether a CRM customer resolved — independent of deal status, this alone
        # decides the sales-pitch voice (see playbook.deck_style_guide).
        customer_scoped = bool(inputs.get("customer_id"))
        grounding = self._grounding(ctx)
        if not author._use_llm():
            return Evidence.error("model required for pptx/docx authoring",
                                  provenance={"capability": "documents", "kind": kind})
        if kind == "docx":
            spec = author.author_doc(goal, grounding=grounding, lang=lang)
            if spec is None:
                return Evidence.error("author unavailable",
                                      provenance={"capability": "documents"})
            sections = spec.get("sections", [])
            ctx.emit(f"アウトライン生成: {len(sections)}セクション")
            for i, s in enumerate(sections, 1):
                ctx.emit(f"セクション{i}: {s.get('heading', '')}")
            ctx.emit("レンダリング中")
            path = output_path("docx", spec.get("_title") or goal[:30], "docx")
            render_docx(spec, path)
            rec = registry.register("docx", path)
            n = len(sections)
            msg = f"文書(DOCX)を生成しました: {rec['filename']}（{n}セクション）。"
            outline = [{"title": s.get("heading", "")} for s in sections]
        else:
            spec = author.author_deck(goal, grounding=grounding, lang=lang,
                                      customer_scoped=customer_scoped)
            if spec is None:
                return Evidence.error("author unavailable",
                                      provenance={"capability": "documents"})
            content_slides = [s for s in spec.get("slides", []) if s.get("layout") != "title"]
            ctx.emit(f"アウトライン生成: {len(content_slides)}スライド")
            for i, s in enumerate(content_slides, 1):
                ctx.emit(f"スライド{i}: {s.get('title', '')}")
            ctx.emit("レンダリング中")
            # HTML-first pipeline (editable PPTX + PDF + HTML); native fallback if no browser.
            from senpai.documents import export
            files = export.render_deck(spec, kind="pptx",
                                       slug=spec.get("_title") or goal[:30], lang=lang)
            recs = _register_deck(registry, files, primary_kind="pptx")
            rec = recs[0]
            n = len(content_slides)
            msg = f"プレゼン(PPTX)を生成しました: {rec['filename']}（{n}スライド）。"
            outline = [{"title": s.get("title", "")} for s in content_slides]
            ctx.emit(f"資料を生成: {rec['filename']}")
            return self._artifact_evidence(rec, ctx, msg, outline=outline, recs=recs)
        ctx.emit(f"資料を生成: {rec['filename']}")
        return self._artifact_evidence(rec, ctx, msg, outline=outline)

    def _artifact_evidence(self, rec: dict, ctx: ExecContext, msg: str,
                           outline: list | None = None,
                           recs: list[dict] | None = None) -> Evidence:
        def _doc(r: dict) -> dict:
            return {"doc_id": r["doc_id"], "kind": r["kind"],
                    "filename": r["filename"], "download_url": r["download_url"]}
        # `document` (singular) stays the primary editable file; `documents` carries the
        # whole export set (PPTX + PDF + HTML) so all surface as download chips.
        data = {"text": msg, "document": _doc(rec),
                "documents": [_doc(r) for r in (recs or [rec])],
                "grounded_on": sorted(
                    ev.capability for ev in ctx.deps.values()
                    if ev.status in ("ok", "partial") and ev.data.get("text"))}
        if outline:
            data["outline"] = outline
        return Evidence.ok(
            data, citations=[*self._citations(ctx), f"doc://{rec['doc_id']}"], status="ok")


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

    def _llm_organize_bucket(self, names: list[str]) -> dict[str, str]:
        from senpai.documents import author
        import json, re
        
        if not author._use_llm() or not names:
            return {n: _organize_bucket(n) for n in names}
            
        prompt = (
            "You are an assistant organizing a user's files. "
            "Given the list of filenames below, assign a single short folder name to each file based on its likely content. "
            "Use standard categories like 'quotes', 'proposals', 'meeting-notes', 'reports', 'contracts', "
            "or create custom descriptive ones like 'invoices', 'research', 'specs'. "
            "Return strictly a JSON object mapping the exact filename to the folder name. No prose.\n\n"
            "Files:\n" + "\n".join(f"- {n}" for n in names)
        )
        
        try:
            out = author._complete(prompt)
            if out:
                m = re.search(r"\{.*\}", out, re.DOTALL)
                if m:
                    mapping = json.loads(m.group(0))
                    return {n: str(mapping.get(n, _organize_bucket(n))).strip("/") for n in names}
        except Exception:
            pass
            
        return {n: _organize_bucket(n) for n in names}

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.workspace import sandbox
        docs = sandbox.list_documents()
        root = sandbox.workspace_root()
        
        # Only reorganize files sitting at the ROOT (don't churn already-filed docs).
        root_files = [p for p in docs if "/" not in sandbox.rel(p) and "\\" not in sandbox.rel(p)]
        
        if root_files:
            file_to_folder = self._llm_organize_bucket([p.name for p in root_files])
        else:
            file_to_folder = {}

        moves: list[tuple[str, str]] = []
        for p in root_files:
            rel = sandbox.rel(p)
            folder = file_to_folder.get(p.name, _organize_bucket(p.name))
            dest = f"{folder}/{p.name}"
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
                KnowledgeCapability(), SolutionsCapability(), WebCapability(),
                DocumentsCapability(), WorkspaceWriteCapability(),
                WorkspaceOrganizeCapability()):
        reg.register(cap)
    return reg
