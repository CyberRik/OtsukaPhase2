"""Tests for hybrid semantic retrieval (BM25 by default; dense gated).

The suite runs BM25-only (see conftest) so it's hermetic — no model download. The
dense path is covered only when SENPAI_TEST_DENSE=1 and the committed vectors exist.
"""
from __future__ import annotations

import os

import pytest

from senpai import config
from senpai.retrieval import semantic
from senpai.retrieval.playbook import retrieve_playbook
from senpai.tools import impl


def test_bm25_mode_active_by_default():
    # conftest forces BM25-only; the index must be present for these tests.
    assert "activities" in semantic.available_corpora()
    assert semantic.mode() in ("BM25", "keyword")


def test_search_finds_lexical_match_offline():
    hits = semantic.semantic_search("予算が厳しい", corpus="activities", limit=5)
    assert hits
    assert all("score" in h and "deal_id" in h for h in hits)
    # a budget-stall query should surface budget-stall notes near the top
    assert any("予算" in h.get("text", "") for h in hits[:5])


def test_empty_query_returns_nothing():
    assert semantic.semantic_search("", corpus="activities") == []


def test_unknown_corpus_is_empty_not_error():
    assert semantic.semantic_search("予算", corpus="does_not_exist") == []


def test_playbook_retrieval_keeps_shape_and_filters_by_tag():
    hits = retrieve_playbook(query="決裁者が見えない", tags=["決裁者未特定"], limit=3)
    assert hits and len(hits) <= 3
    # unchanged return shape: raw playbook dicts
    assert all({"entry_id", "situation_tags", "text", "author_rep_id"} <= set(e) for e in hits)


def test_search_notes_tool_formats_hits():
    out = impl.dispatch("search_notes", {"query": "サーバーの設置環境を確認", "limit": 3})
    assert isinstance(out, str)
    assert "日報" in out or "見つかりません" in out


def test_keyword_fallback_when_no_bm25(monkeypatch):
    # Simulate rank_bm25 absent → pure keyword substring layer still returns hits.
    monkeypatch.setattr(semantic, "HAS_BM25", False)
    semantic.reload()
    hits = semantic.semantic_search("予算", corpus="activities", limit=3)
    assert hits
    semantic.reload()


@pytest.mark.skipif(os.environ.get("SENPAI_TEST_DENSE") != "1",
                    reason="dense path needs the embedding model (set SENPAI_TEST_DENSE=1)")
def test_dense_hybrid_beats_lexical_on_paraphrase():
    pytest.importorskip("fastembed")
    config.USE_EMBEDDINGS = True
    semantic.reload()
    try:
        # paraphrase with no shared surface tokens with the seed note ("予算が厳しい")
        hits = semantic.semantic_search("お金が足りず話が前に進まない", "activities", 5)
        assert hits
        assert any("予算" in h.get("text", "") for h in hits[:5])
    finally:
        config.USE_EMBEDDINGS = False
        semantic.reload()
