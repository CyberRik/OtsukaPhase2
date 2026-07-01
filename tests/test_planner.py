"""Tests for the minimal LLMPlanner (milestone 1: document generation).

All GPU-free: conftest leaves SENPAI_USE_LLM off, so the planner uses its
deterministic `heuristic_selection` and the proposal path (proposal.generate) runs
without a model. The authored pptx/docx path needs a model, so we only assert it
degrades gracefully (a clear error fragment, never a crash). Generated files are
redirected to a tmp dir so the committed seed is never touched.
"""
from __future__ import annotations

import threading

import pytest

from senpai import config
from senpai.orchestration import ExecContext
from senpai.orchestration.evidence import Evidence
from senpai.planner import LLMPlanner, document_plan, run_document_goal
from senpai.planner.capabilities import DocumentsCapability
from senpai.planner.selection import heuristic_selection


@pytest.fixture(autouse=True)
def _tmp_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GENERATED_DIR", tmp_path / "generated")
    return tmp_path / "generated"


@pytest.fixture
def _sample_workspace(tmp_path, monkeypatch):
    """A hermetic workspace so file-grounding tests never depend on the configured
    (real) WORKSPACE_ROOT. sandbox.workspace_root() re-reads config each call."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "murata_printing_display_quote.txt").write_text(
        "有限会社村田印刷 様\nディスプレイ案件 見積書 (D001)\n"
        "27インチモニター (MON27) × 4台: ¥204,000\n", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE_ROOT", ws)
    return ws


# --- selection: which capabilities, which doc kind, which (grounded) entity -----
def test_selection_proposal_resolves_real_deal():
    sel = heuristic_selection("Generate a proposal for D001")
    assert sel.doc_kind == "proposal"
    assert sel.deal_id == "D001"                 # deterministically grounded, not invented
    assert "crm" in sel.capabilities
    assert "conversation" in sel.capabilities    # always gathered
    assert "knowledge" in sel.capabilities       # proposals get playbook grounding


def test_selection_general_deck_is_web_gated_no_crm():
    sel = heuristic_selection("best gaming laptops under 1000000 yen deck")
    assert sel.doc_kind == "pptx"
    assert sel.deal_id is None and sel.customer_id is None
    assert "web" in sel.capabilities             # external/factual topic
    assert "crm" not in sel.capabilities         # nothing internal to ground on


def test_selection_customer_name_resolves_to_open_deal():
    # A named CRM customer with no explicit deal id still grounds a proposal on its
    # primary open deal — the planner resolves the id, the model never guesses it.
    sel = heuristic_selection("藤本食品向けの提案書を作成")
    assert sel.doc_kind == "proposal"
    assert sel.deal_id is not None
    assert sel.customer_id is not None


# --- plan: the fixed two-level capability DAG -----------------------------------
def test_plan_dag_documents_depends_on_all_gather():
    sel = heuristic_selection("Generate a proposal for D001")
    plan = document_plan(sel)
    plan.validate()                              # ids unique, deps known, acyclic
    ids = {t.id for t in plan.tasks}
    assert "documents" in ids
    doc = next(t for t in plan.tasks if t.id == "documents")
    gather = {t.id for t in plan.tasks if t.id != "documents"}
    assert set(doc.depends_on) == gather         # terminal waits for every source
    for t in plan.tasks:                         # gather tasks are independent (level 0)
        if t.id != "documents":
            assert t.depends_on == frozenset()
    assert doc.op == "proposal" and doc.policy.retries == 0   # WRITE: never auto-repeat


def test_planner_plan_returns_execution_plan():
    plan = LLMPlanner().plan("Generate a proposal for D001")
    plan.validate()
    assert any(t.capability == "documents" for t in plan.tasks)


# --- end to end: plan → engine → bundle → artifact (proposal path, GPU-free) -----
def test_run_document_goal_produces_registered_proposal(_tmp_generated, _sample_workspace):
    from senpai.documents import registry
    convo = [
        {"role": "user", "content": "村田印刷にいくら見積もった？"},
        {"role": "tool", "content": "ワークスペース文書: 有限会社村田印刷 ¥204,000"},
        {"role": "assistant", "content": "村田印刷への見積もりは¥204,000です。"},
        {"role": "user", "content": "make a proposal for Murata Printing 村田印刷"},
    ]
    result = run_document_goal("make a proposal for Murata Printing 村田印刷",
                               conversation=convo)

    # The plan wired a documents task depending on the gather capabilities.
    assert result["selection"]["doc_kind"] == "proposal"
    assert result["selection"]["deal_id"] == "D001"
    assert any(p["id"] == "documents" and p["depends_on"] for p in result["plan"])

    # A real file was produced and registered for download.
    doc = result["document"]
    assert doc and doc["filename"].endswith(".pptx")
    assert registry.get(doc["doc_id"]) is not None
    assert list(_tmp_generated.glob("*.pptx"))

    # It was grounded on the gathered bundle — the conversation + CRM at least, and
    # the Murata local file (workspace matched on the goal). NOT re-gathered inside
    # the tool: this is the capability graph feeding the artifact.
    assert "conversation" in result["grounded_on"]
    assert "crm" in result["grounded_on"]
    assert "workspace" in result["grounded_on"]


# --- Documents capability consumes the bundle (does not re-gather) ---------------
def _ctx(deps: dict) -> ExecContext:
    return ExecContext(task_id="documents", inputs={}, deps=deps,
                       emit=lambda _m: None, expand=lambda _t: None,
                       cancel=threading.Event(), deadline=9e18)


def test_documents_grounding_assembles_deps_in_order():
    cap = DocumentsCapability()
    deps = {
        "web": Evidence(status="ok", data={"text": "W", "label": "Web検索"}, capability="web"),
        "conversation": Evidence(status="ok", data={"text": "C", "label": "会話"},
                                 capability="conversation"),
        "crm": Evidence(status="ok", data={"text": "R", "label": "社内データ"}, capability="crm"),
    }
    g = cap._grounding(_ctx(deps))
    # Most-specific first: conversation, then crm, then web (workspace/knowledge absent).
    assert g.index("会話") < g.index("社内データ") < g.index("Web検索")


# --- chat routing: document goals go to the planner, everything else doesn't ----
def test_document_goal_router_precision():
    from senpai.api.server import _is_document_goal
    routed = [
        "make a proposal for Murata Printing", "create a deck on gaming laptops",
        "generate a pptx for D168", "村田印刷の提案書を作って", "スライドを作成して",
        "write me a report on Q4 trends", "put together a slide deck for the client",
    ]
    not_routed = [
        "draft an email to the client", "make a quote for 3 monitors",
        "tell me about Murata Printing", "what did we quote yamato in my files?",
        "schedule a meeting with endo", "D168 のリスクを教えて",
        "稟議書を作成して", "make a ringisho for D001",   # ringisho keeps its own tool
    ]
    assert all(_is_document_goal(m) for m in routed)
    assert not any(_is_document_goal(m) for m in not_routed)


def test_selector_deal_id_is_authoritative():
    # A deal picked in the selector overrides text resolution and forces a proposal.
    from senpai.planner.selection import heuristic_selection
    sel = heuristic_selection("make a deck about our storage solutions", deal_hint="D001")
    assert sel.deal_id == "D001"
    assert sel.doc_kind == "proposal"


def test_authored_deck_degrades_without_model(_tmp_generated):
    # pptx authoring needs a model; with SENPAI_USE_LLM off it must return a clean
    # error fragment (no crash, no file).
    cap = DocumentsCapability()
    ev = cap.run("pptx", {"goal": "best gaming laptops"}, _ctx({}))
    assert ev.status == "error"
    assert not _tmp_generated.exists() or not list(_tmp_generated.glob("*.pptx"))


# --- workspace WRITE terminals: note + organize (hermetic, GPU-free) -------------
def test_organize_previews_then_applies(tmp_path, monkeypatch):
    from senpai import config
    from senpai.planner import run_document_goal

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "murata_見積書.txt").write_text("q", encoding="utf-8")
    (ws / "yamato_proposal.md").write_text("p", encoding="utf-8")
    (ws / "endo_議事録.md").write_text("m", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE_ROOT", ws)

    # Preview never moves anything.
    prev = run_document_goal("organize my files")
    assert prev["selection"]["doc_kind"] == "organize"
    assert {p.name for p in ws.iterdir() if p.is_file()} == {
        "murata_見積書.txt", "yamato_proposal.md", "endo_議事録.md"}

    # Apply buckets by topic and leaves only subfolders at the root.
    run_document_goal("organize my files and apply")
    assert (ws / "quotes" / "murata_見積書.txt").is_file()
    assert (ws / "proposals" / "yamato_proposal.md").is_file()
    assert (ws / "meeting-notes" / "endo_議事録.md").is_file()
    assert not [p for p in ws.iterdir() if p.is_file()]  # nothing loose at the root


def test_organize_move_is_sandbox_safe_and_no_overwrite(tmp_path, monkeypatch):
    from senpai import config
    from senpai.workspace import sandbox
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("2", encoding="utf-8")
    with pytest.raises(sandbox.SandboxError):
        sandbox.move_within("a.txt", "../escape.txt")         # can't leave the root
    with pytest.raises(sandbox.SandboxError):
        sandbox.move_within("a.txt", "sub/a.txt")             # never overwrites


def test_note_write_persists_grounded_file(tmp_path, monkeypatch):
    from senpai import config
    from senpai.planner import run_document_goal

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(config, "WORKSPACE_ROOT", ws)
    monkeypatch.setattr(config, "GENERATED_DIR", tmp_path / "gen")
    convo = [
        {"role": "assistant", "content": "村田印刷は¥204,000の見積を提示済み。"},
        {"role": "user", "content": "save this as a note to murata_followup.md"},
    ]
    r = run_document_goal("save this as a note to murata_followup.md", conversation=convo)
    assert r["selection"]["doc_kind"] == "note"
    saved = ws / "murata_followup.md"
    assert saved.is_file()
    assert "204,000" in saved.read_text(encoding="utf-8")     # grounded on the conversation


# --- opt-in integration: exercise the REAL configured workspace (skipped if absent) --
def test_real_workspace_is_searchable_if_configured():
    """Unit tests are hermetic on purpose; this one intentionally hits the *configured*
    WORKSPACE_ROOT so 'does it see my real folder' is covered — skipped when that folder
    doesn't exist (CI / another machine), so it never makes the suite fragile."""
    from senpai.workspace import sandbox
    root = sandbox.workspace_root()
    if not root.is_dir():
        pytest.skip(f"configured WORKSPACE_ROOT does not exist: {root}")
    docs = sandbox.list_documents()
    # Whatever is there, discovery must stay inside the root and never surface our own
    # generated output (the feedback-loop guard).
    assert all("generated" not in sandbox.rel(p).lower().split("/")[0] for p in docs)
