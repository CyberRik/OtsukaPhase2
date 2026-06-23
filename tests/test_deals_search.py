"""Tests for the grounded faceted deal search (senpai.retrieval.deals + tool).

Hermetic: pure store reads over the committed seed. Asserts that every returned
row truly satisfies the requested facets (so the tool can never surface a deal the
filters exclude) and that no-match returns guidance rather than nothing.
"""
from __future__ import annotations

from senpai import config
from senpai.data import store
from senpai.retrieval.deals import deal_facets, find_deals, outcome_breakdown
from senpai.tools import impl


def test_facets_are_discovered_from_data():
    f = deal_facets()
    # values come from the seed, not a hardcoded list
    assert "サーバー" in f["product_category"]
    assert "中規模" in f["size"]
    assert set(f["outcome"]) == {"won", "lost", "open"}


def test_category_filter_returns_only_that_category():
    hits = find_deals(product_category="サーバー", limit=0)
    assert hits
    assert all(d["product_category"] == "サーバー" for d in hits)


def test_size_filter_joins_to_customer():
    hits = find_deals(size="中規模", limit=0)
    assert hits
    for d in hits:
        cust = store.get_customer(d["customer_id"])
        assert cust and cust["size"] == "中規模"


def test_outcome_won_only_returns_confirmed_ranks():
    hits = find_deals(outcome="won", limit=0)
    assert hits
    assert all(d["order_rank"] in config.WON_RANKS for d in hits)


def test_combined_facets_are_a_subset():
    cat = find_deals(product_category="サーバー", limit=0)
    combined = find_deals(product_category="サーバー", size="中規模", outcome="won", limit=0)
    assert len(combined) <= len(cat)
    for d in combined:
        cust = store.get_customer(d["customer_id"])
        assert d["product_category"] == "サーバー"
        assert cust["size"] == "中規模"
        assert d["order_rank"] in config.WON_RANKS


def test_amount_band_is_respected():
    hits = find_deals(min_amount=1_000_000, limit=0)
    assert hits
    assert all((d.get("total_order_amount", 0) or 0) >= 1_000_000 for d in hits)


def test_partial_industry_substring_match():
    # '製造' should match the '製造' industry without needing an exact token
    hits = find_deals(industry="製造", limit=0)
    assert hits
    for d in hits:
        cust = store.get_customer(d["customer_id"])
        assert "製造" in cust.get("industry", "")


def test_results_sorted_by_amount_desc():
    hits = find_deals(product_category="ソフトウェア", limit=0)
    amounts = [d.get("total_order_amount", 0) or 0 for d in hits]
    assert amounts == sorted(amounts, reverse=True)


def test_limit_caps_results():
    assert len(find_deals(limit=3)) == 3


def test_outcome_breakdown_sums_to_total():
    hits = find_deals(product_category="サーバー", limit=0)
    bd = outcome_breakdown(hits)
    assert bd["won"] + bd["lost"] + bd["open"] + bd["other"] == len(hits)


def test_tool_reports_breakdown_and_lists_deals():
    out = impl.dispatch("find_deals", {"product_category": "サーバー", "outcome": "won", "limit": 5})
    assert isinstance(out, str) and not out.startswith("[error]")
    assert "受注" in out and "サーバー" in out


def test_tool_no_match_returns_facet_guidance_not_invention():
    # a value absent from the data must not fabricate deals
    out = impl.dispatch("find_deals", {"product_category": "存在しないカテゴリ"})
    assert "指定可能な値" in out
    assert "サーバー" in out  # lists real categories to use instead
