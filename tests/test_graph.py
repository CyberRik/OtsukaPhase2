"""Tests for the SPR knowledge graph + multi-hop queries (deterministic, GPU-free)."""
from __future__ import annotations

from senpai.data import store
from senpai.graph import build, query as gq
from senpai.tools import impl


def test_graph_has_every_entity_kind():
    s = build.stats()
    k = s["by_kind"]
    assert k["rep"] == len(store.all_reps())
    assert k["customer"] == len(store.all_customers())
    assert k["deal"] == len(store.all_deals())
    assert k["product"] == len(store.all_products())
    # one OWNS + one FOR edge per deal
    assert s["by_rel"]["OWNS"] == len(store.all_deals())
    assert s["by_rel"]["FOR"] == len(store.all_deals())


def test_reps_who_win_returns_sorted_winrates():
    rows = gq.reps_who_win(category="サーバー")
    assert rows
    assert all({"rep_id", "win_rate", "won", "closed"} <= set(r) for r in rows)
    rates = [r["win_rate"] for r in rows]
    assert rates == sorted(rates, reverse=True)        # best win-rate first
    assert all(0.0 <= r["win_rate"] <= 1.0 for r in rows)
    assert all(r["closed"] >= r["won"] for r in rows)


def test_reps_who_win_industry_filter_narrows():
    broad = gq.reps_who_win(category="サーバー")
    narrow = gq.reps_who_win(category="サーバー", industry="製造")
    broad_closed = sum(r["closed"] for r in broad)
    narrow_closed = sum(r["closed"] for r in narrow)
    assert narrow_closed <= broad_closed              # adding a filter can only narrow


def test_account_graph_for_matsuda_c28():
    g = gq.account_graph("C28")
    assert g["status"] == "found"
    assert "松田" in g["name"]
    assert g["deals"]                                  # C28 has a seeded open pipeline
    assert g["reps"]


def test_connections_finds_a_path():
    r = gq.connections("C28", "SRV20")
    assert r["status"] in ("found", "no_path")
    if r["status"] == "found":
        assert r["hops"] >= 1
        assert r["path"][0]["id"] == "C28"
        assert r["path"][-1]["id"] == "SRV20"


def test_similar_by_graph_excludes_self_and_scores():
    sims = gq.similar_by_graph("D005", limit=5)
    assert "D005" not in [s["deal_id"] for s in sims]
    assert all(s["score"] > 0 for s in sims)


def test_query_graph_tool_dispatch():
    out = impl.dispatch("query_graph", {"intent": "reps_who_win", "category": "サーバー"})
    assert "勝ちパターン" in out or "見つかりません" in out
    bad = impl.dispatch("query_graph", {"intent": "nonsense"})
    assert "error" in bad or "未知" in bad
