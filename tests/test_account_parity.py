"""M3 golden regression: the account-commentary gather now runs on the engine; it
must reproduce `build_account_context` byte-for-byte.

The commentary artifact is driven entirely by `account_commentary_prompt(context_text)`,
so identical (context_text, meta) ⇒ identical prompt ⇒ identical artifact. We assert
that across many real accounts, plus the not-found and degraded-failure paths.
"""
from __future__ import annotations

import pytest

from senpai import config
from senpai.account import build_account_context
from senpai.account.gather import gather_account_context
from senpai.data import store

TODAY = config.today()


def _customer_ids(limit=60):
    return [c["customer_id"] for c in store.all_customers()[:limit]]


@pytest.mark.parametrize("customer_id", _customer_ids(), ids=lambda c: c)
@pytest.mark.parametrize("lang", ["ja", "en"])
def test_account_context_parity(customer_id, lang):
    legacy_text, legacy_meta = build_account_context(customer_id, today=TODAY, lang=lang)
    orch_text, orch_meta = gather_account_context(customer_id, lang=lang, today=TODAY)
    assert orch_text == legacy_text
    assert orch_meta == legacy_meta


def test_account_not_found_parity():
    cid = "ZZZ-nonexistent"
    legacy = build_account_context(cid, today=TODAY)
    orch = gather_account_context(cid, today=TODAY)
    assert orch == legacy
    assert orch[1]["has_account"] is False


def test_account_gather_degrades_on_failure(monkeypatch):
    # If the context builder blows up, the gather degrades to the not-found shape
    # (the route then streams account_not_found) instead of crashing the request.
    import senpai.account.capabilities as caps

    def boom(*a, **k):
        raise RuntimeError("simulated account outage")

    monkeypatch.setattr(caps, "build_account_context", boom)
    cid = _customer_ids(1)[0]
    text, meta = gather_account_context(cid, today=TODAY)
    assert meta["has_account"] is False
    assert "NO MATCHING ACCOUNT" in text


def test_account_emits_progress_event():
    # The engine surfaces a task.progress for the gather (future timeline use); the
    # route does not forward it, so the wire contract is unchanged.
    cid = _customer_ids(1)[0]
    events = []
    gather_account_context(cid, today=TODAY, emit=events.append)
    assert any(e["type"] == "task.progress" for e in events)
