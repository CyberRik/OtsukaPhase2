"""SessionFocus — the entity resolved from the published conversation.

Focus is derived from the ids REAL tool results emitted (D001 / C13), not from
fuzzy name matching, so it's authoritative and safe for grounding to trust.
"""
from __future__ import annotations

from senpai.data import store
from senpai.tools import conversation as conv
from senpai.tools.focus import SessionFocus, session_focus

DEAL = "D001"
CUST = store.get_deal(DEAL)["customer_id"]  # C13


def test_focus_empty_without_conversation():
    conv.set_conversation(None)
    assert session_focus() == SessionFocus()
    assert not session_focus()


def test_focus_resolves_deal_and_its_customer_from_tool_result():
    """A deal id in a tool result pins both the deal and (via the store) its customer
    — 'that deal we discussed' becomes a lookup, not a re-inference."""
    conv.set_conversation([
        {"role": "user", "content": "この案件の状況は？"},
        {"role": "tool", "content": f"{DEAL} 案件 / 受注ランクA / ¥204,000"},
        {"role": "assistant", "content": "進行中です。"},
    ])
    try:
        f = session_focus()
    finally:
        conv.set_conversation(None)
    assert f.deal_id == DEAL
    assert f.customer_id == CUST
    assert f.last_quote == "¥204,000"
    assert f.customer_name == store.customer_name(CUST)


def test_focus_prefers_most_recent_deal():
    conv.set_conversation([
        {"role": "tool", "content": "D002 古い案件"},
        {"role": "tool", "content": f"{DEAL} 新しい案件"},
    ])
    try:
        assert session_focus().deal_id == DEAL   # newest-first
    finally:
        conv.set_conversation(None)


def test_focus_ignores_fuzzy_names_only_ids():
    """A company NAMED in free text but never resolved to an id (no tool emitted its
    id — it isn't a CRM customer) must NOT become focus. This is the guard against
    the wrong-company hallucination: focus never fuzzy-matches names."""
    conv.set_conversation([
        {"role": "user", "content": "村田印刷の提案書を作って"},
        {"role": "tool", "content": "ワークスペース文書: 有限会社村田印刷 ¥204,000"},
        {"role": "assistant", "content": "村田印刷の見積もりは¥204,000です。"},
    ])
    try:
        f = session_focus()
    finally:
        conv.set_conversation(None)
    assert f.deal_id is None
    assert f.customer_id is None          # no id was ever resolved for 村田印刷
    assert f.last_quote == "¥204,000"     # but a figure is still captured


def test_focus_ignores_invalid_ids():
    conv.set_conversation([{"role": "tool", "content": "D9999 存在しない / C9999 無効"}])
    try:
        f = session_focus()
    finally:
        conv.set_conversation(None)
    assert f.deal_id is None
    assert f.customer_id is None
