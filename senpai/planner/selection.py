"""What the planner decides: a `Selection` — which capabilities to gather from and
what document to produce — plus the deterministic resolver that grounds it.

The LLM's job (in llm_planner.py) is to pick *which capabilities* are worth
gathering. IDs are never trusted to the model: the customer/deal a document is
grounded in is resolved here, deterministically, from the store (the project's
"never invent an ID" rule). So even a hallucinated capability list can only widen
or narrow the gather — it can never point the document at the wrong deal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from senpai import config
from senpai.data import store

# The gather capabilities the planner may select from (documents is always the
# terminal, so it is not part of the selectable gather set).
GATHER_CAPABILITIES = ("conversation", "workspace", "crm", "knowledge", "web")
# What the terminal produces. proposal/pptx/docx = generate an artifact file; note =
# write a text file into the workspace; organize = tidy the workspace on disk.
DOC_KINDS = ("proposal", "pptx", "docx", "note", "organize")

_DEAL_ID_RE = re.compile(r"\bD\d{3}\b", re.IGNORECASE)
_PROPOSAL_CUES = ("提案", "proposal", "提案書")
# 稟議 (ringisho) is intentionally NOT here: it has its own dedicated template/tool
# (generate_ringisho) and is routed to the ReAct loop, not the planner.
_DOCX_CUES = ("文書", "報告書", "レポート", "docx", "document", "report")
# External/factual cue (stale-in-weights topics) — reuse the doc tools' own heuristic.
from senpai.tools.impl import _auto_web  # noqa: E402


# --- planner intent detection (the router's source of truth) ----------------
# Document GENERATION: a create verb + a document noun. 稟議 excluded (own tool).
_DOC_VERB = (r"(?:make|create|generate|build|draft|write|produce|prepare|"
             r"put\s+together|作って|作成|作る|生成|書いて|まとめて|用意|つくって)")
_DOC_NOUN = (r"(?:proposal|deck|slides?|slide\s?deck|presentation|power\s?point|"
             r"pptx?|ppt|docx?|word\s+doc(?:ument)?|document|report|"
             r"提案書|提案|スライド|資料|プレゼン(?:テーション)?|文書|報告書|レポート)")
_DOC_GOAL_RE = re.compile(
    _DOC_VERB + r"\b.{0,40}?" + _DOC_NOUN + r"|" + _DOC_NOUN + r".{0,20}?(?:を|の)?\s*" + _DOC_VERB,
    re.IGNORECASE)
_RINGISHO_RE = re.compile(r"稟議|ringisho", re.IGNORECASE)

# ORGANIZE: tidy/sort/reorganize the workspace on disk (a WRITE that moves files).
_ORGANIZE_RE = re.compile(
    r"\b(?:organi[sz]e|reorgani[sz]e|tidy(?:\s?up)?|clean\s?up|sort|file\s+away|declutter)\b"
    r".{0,30}?(?:files?|documents?|docs?|folder|workspace)|"
    r"\b(?:put|move|place)\b.{1,40}?\b(?:in|into|under|to|inside)\b.{1,30}?(?:folder|directory)?|"
    r"(?:ファイル|資料|ドキュメント|文書|フォルダ|ワークスペース).{0,10}?"
    r"(?:整理|片付け|仕分け|フォルダ分け|分類|移動)|"
    r"(?:整理|片付け|仕分け|フォルダ分け|分類|移動)(?:して|する)?", re.IGNORECASE)

# NOTE: save/write a short text file INTO the workspace (not a generated artifact).
_NOTE_RE = re.compile(
    r"\b(?:save|jot(?:\s+down)?|record|note\s+down|write\s+(?:a\s+|this\s+)?(?:note|down))\b"
    r".{0,40}?(?:my\s+)?(?:files?|documents?|docs?|workspace|note|\.md|\.txt)|"
    r"(?:save|write|append).{0,20}?(?:to|into)\s+[\w./-]+\.(?:md|txt|json|csv)|"
    r"(?:メモ|ノート|記録)(?:を|に)?.{0,10}?(?:保存|作成|残|書|追記)|"
    r"(?:ファイル|資料|文書)(?:に|へ).{0,10}?(?:保存|書き込|追記|記録)", re.IGNORECASE)

# Explicit "actually do it" for the destructive organize (otherwise preview only).
_APPLY_RE = re.compile(r"\b(?:apply|do\s+it|go\s+ahead|confirm|execute)\b|実行|適用|やって",
                       re.IGNORECASE)
# A broader affirmation, only ever consulted right after an organize PREVIEW (so a
# bare "yes"/"go ahead"/"はい" continues and applies the pending reorganize).
_AFFIRM_RE = re.compile(
    r"\b(?:yes|yeah|yep|ok|okay|sure|go\s+ahead|do\s+it|apply|proceed|confirm|"
    r"execute|please\s+do|go\s+for\s+it)\b|はい|お願い|やって|実行|適用|進めて|それで",
    re.IGNORECASE)
# The marker the organize PREVIEW writes into its assistant reply (see
# WorkspaceOrganizeCapability); its presence in the last assistant turn is what makes
# a following affirmation mean "apply the reorganize".
_ORGANIZE_PREVIEW_MARK = "【整理プレビュー"


def _recent_assistant_texts(history: list | None, limit: int = 3) -> list[str]:
    """The most recent assistant messages' texts, so continuation detection works
    even if the model hallucinated a turn in between."""
    if not history:
        return []
    texts = []
    for item in reversed(history):
        role = getattr(item, "role", None)
        content = getattr(item, "content", None)
        if role is None and isinstance(item, dict):
            role, content = item.get("role"), item.get("content")
        if role == "assistant":
            texts.append(content or "")
            if len(texts) >= limit:
                break
    return texts


def _organize_apply_continuation(message: str, history: list | None) -> bool:
    """True when the user is confirming a pending organize preview (an affirmation
    immediately after the preview was shown, checking up to 3 turns back)."""
    if not bool(_AFFIRM_RE.search(message or "")):
        return False
    recent = _recent_assistant_texts(history, limit=3)
    return any(_ORGANIZE_PREVIEW_MARK in text for text in recent)


def is_organize_goal(message: str, history: list | None = None) -> bool:
    return (bool(_ORGANIZE_RE.search(message or ""))
            or _organize_apply_continuation(message, history))


def is_note_goal(message: str) -> bool:
    return bool(_NOTE_RE.search(message or ""))


def is_document_goal(message: str) -> bool:
    m = message or ""
    if _RINGISHO_RE.search(m):
        return False
    return bool(_DOC_GOAL_RE.search(m))


def is_planner_goal(message: str, history: list | None = None) -> bool:
    """Any goal the LLMPlanner owns: organize / note-write / document generation.
    Order matters — organize and note are checked first because their phrasings can
    also contain a document noun ('organize my documents')."""
    return (is_organize_goal(message, history) or is_note_goal(message)
            or is_document_goal(message))


@dataclass(frozen=True)
class Selection:
    """The plan the LLMPlanner emits: the capability set to gather from + the
    document to build (kind + the deterministically-resolved entity it grounds in)."""
    goal: str
    capabilities: tuple[str, ...]          # subset of GATHER_CAPABILITIES
    doc_kind: str                          # one of DOC_KINDS
    deal_id: str | None = None
    customer_id: str | None = None
    target: str = ""                       # display name of the entity in focus
    lang: str = "ja"
    title: str = ""
    reason: str = ""                       # why these capabilities (observability)
    confirm: bool = False                  # apply a destructive op (organize); else preview
    path: str = ""                         # target file for a note write (optional)

    def with_capabilities(self, caps) -> "Selection":
        ordered = tuple(c for c in GATHER_CAPABILITIES if c in set(caps))
        return replace(self, capabilities=ordered)


def _resolve_entity(goal: str, deal_hint: str | None = None) -> tuple[str | None, str | None, str]:
    """(deal_id, customer_id, display_target) for the document, from the store.
    A `deal_hint` (e.g. the deal the rep picked in the selector) is authoritative;
    then an explicit D### in the goal; otherwise a customer name resolves to its
    primary open deal (largest amount) so a proposal can be grounded. None/None when
    the entity isn't in the CRM (e.g. a workspace-only company) — then a free deck
    grounds on the workspace/conversation instead."""
    if deal_hint:
        d = store.get_deal(deal_hint.strip().upper())
        if d:
            did = d["deal_id"]
            return did, d["customer_id"], store.customer_name(d["customer_id"])
    m = _DEAL_ID_RE.search(goal or "")
    if m:
        did = m.group(0).upper()
        d = store.get_deal(did)
        if d:
            return did, d["customer_id"], store.customer_name(d["customer_id"])
    cust = store.match_customer_in_text(goal or "")
    if not cust:
        return None, None, ""
    cid = cust["customer_id"]
    open_deals = [d for d in store.deals_for_customer(cid)
                  if config.is_open_rank(d.get("order_rank"))]
    open_deals.sort(key=lambda d: d.get("total_order_amount", 0), reverse=True)
    deal_id = open_deals[0]["deal_id"] if open_deals else None
    return deal_id, cid, cust.get("name", "")


def _pick_doc_kind(goal: str, deal_id: str | None, history: list | None = None) -> str:
    g = (goal or "")
    # Workspace ops win over document generation (their phrasing overlaps).
    if is_organize_goal(g, history):
        return "organize"
    if is_note_goal(g):
        return "note"
    if deal_id or any(c in g.lower() or c in g for c in _PROPOSAL_CUES):
        # A grounded proposal needs a deal; without one it degrades to a free deck.
        return "proposal" if deal_id else "pptx"
    if any(c in g.lower() or c in g for c in _DOCX_CUES):
        return "docx"
    return "pptx"


def _lang_of(goal: str) -> str:
    """JA unless the goal has no CJK at all (then EN)."""
    return "ja" if re.search(r"[぀-ヿ一-鿿]", goal or "") else "ja"


def heuristic_selection(goal: str, deal_hint: str | None = None, history: list | None = None) -> Selection:
    """Deterministic capability selection — the default, and the fallback whenever
    the LLM is off or returns junk. Always gathers conversation (session context);
    adds workspace (self-gated on a real file match), CRM when an entity resolved,
    knowledge for proposals (playbook grounding), and web for external/factual
    topics with no internal entity."""
    deal_id, customer_id, target = _resolve_entity(goal, deal_hint)
    doc_kind = _pick_doc_kind(goal, deal_id, history)

    # Organize is self-contained (it inspects the workspace itself) — no gather.
    # Apply when the goal itself says so ("...and apply") OR when it's an affirmation
    # confirming a pending preview ("go ahead"); otherwise preview (never move silently).
    if doc_kind == "organize":
        confirm = (bool(_APPLY_RE.search(goal or ""))
                   or _organize_apply_continuation(goal, history))
        return Selection(goal=goal, capabilities=(), doc_kind="organize",
                         lang=_lang_of(goal), confirm=confirm,
                         reason="heuristic: organize workspace ("
                                + ("apply" if confirm else "preview") + ")")

    caps = ["conversation", "workspace"]
    if customer_id or deal_id:
        caps.append("crm")
    if doc_kind == "proposal":
        caps.append("knowledge")
    if _auto_web(goal) and not (customer_id or deal_id):
        caps.append("web")

    return Selection(
        goal=goal, capabilities=tuple(caps), doc_kind=doc_kind,
        deal_id=deal_id, customer_id=customer_id, target=target,
        lang=_lang_of(goal),
        reason="heuristic: " + ("entity in CRM" if (customer_id or deal_id)
                                else "no CRM entity — workspace/conversation grounded"))


def ground_selection(goal: str, caps, doc_kind: str, reason: str = "",
                     deal_hint: str | None = None, history: list | None = None) -> Selection:
    """Build a Selection from an LLM-chosen capability set + doc_kind, but re-ground
    the entity/IDs deterministically and enforce invariants: conversation is always
    gathered; a `proposal` with no resolvable deal degrades to a free `pptx`; CRM is
    only kept when an entity actually resolved."""
    deal_id, customer_id, target = _resolve_entity(goal, deal_hint)
    if doc_kind not in DOC_KINDS:
        doc_kind = _pick_doc_kind(goal, deal_id, history)
    if doc_kind == "proposal" and not deal_id:
        doc_kind = "pptx"  # can't ground a proposal without a deal

    chosen = {c for c in caps if c in set(GATHER_CAPABILITIES)}
    chosen.add("conversation")             # session context is always worth gathering
    if "crm" in chosen and not (customer_id or deal_id):
        chosen.discard("crm")              # nothing for CRM to ground on
    if doc_kind == "proposal":
        chosen.add("knowledge")

    return Selection(
        goal=goal, capabilities=tuple(c for c in GATHER_CAPABILITIES if c in chosen),
        doc_kind=doc_kind, deal_id=deal_id, customer_id=customer_id, target=target,
        lang=_lang_of(goal), reason=reason or "llm-selected")
