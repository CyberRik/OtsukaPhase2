"""Chat-loop guards against tools that look productive but aren't.

1. The answer-as-arg leak: under forced tool_choice the reasoning model sometimes packs
   its whole final answer (plus a stray <function=finish> tag) into a tool argument
   instead of finishing. That runs a bogus query and makes the turn generate the answer
   twice. `_is_finish_leak` catches it so the loop routes to a single clean synthesis.

2. The confident-but-irrelevant escalation: `route_to_expert` scored every expert
   against a -1 seed, so a question touching nobody's specialty still "matched" whoever
   came first ("Where is the Otsuka Shokai office?" → 田中健太). It must fail instead,
   and its failure must read as non-substantive so the no-evidence guard engages.
"""
from __future__ import annotations

import json

from senpai.llm.client import _is_finish_leak, _is_substantive
from senpai.tools import impl
from senpai.tools.impl import route_to_expert
from senpai.tools.outcomes import is_miss, is_not_found

# The actual shape observed in the D016-vs-D100 trace: the whole answer stuffed into
# the `customer` field, trailing a finish sentinel.
_LEAKED = ('{"customer": "**結論：D100の方が状況は良いです。**\\n\\n| 比較項目 | D016 | D100 |\\n'
           + "あ" * 300 + '\\n\\n<tool_call>\\n<function=finish>"}')


def test_detects_finish_sentinel_in_args():
    assert _is_finish_leak("query_spr", '{"customer": "x <function=finish>"}')
    assert _is_finish_leak("query_spr", '{"customer": "x\\n<tool_call>\\n..."}')
    assert _is_finish_leak("query_spr", '{"note": "reasoning</think> done"}')


def test_detects_answer_sized_arg_blob():
    assert _is_finish_leak("query_spr", _LEAKED)
    assert _is_finish_leak("web_search", '{"q": "' + "x" * 700 + '"}')


def test_legit_short_args_are_not_leaks():
    assert not _is_finish_leak("deal_health", '{"deal_id": "D016"}')
    assert not _is_finish_leak("query_spr", '{"customer": "豊田製作所", "deal_id": "D016"}')
    assert not _is_finish_leak("web_search", '{"q": "Otsuka Shokai 決算 2026"}')
    assert not _is_finish_leak("finish", "{}")


def test_accepts_dict_args_not_just_strings():
    assert _is_finish_leak("query_spr", {"customer": "done <function=finish>"})
    assert not _is_finish_leak("deal_health", {"deal_id": "D016"})


def test_empty_args_are_not_leaks():
    assert not _is_finish_leak("finish", "")
    assert not _is_finish_leak("finish", None)
    assert not _is_finish_leak("finish", {})


# --- route_to_expert relevance gate --------------------------------------------
def test_irrelevant_question_matches_no_expert():
    # None of these touch a specialty tag (ネットワーク/サーバー/セキュリティ/…).
    for q in ("Where is the Otsuka Shokai office located?", "明日の天気は？", "What is 2+2?", ""):
        out = route_to_expert(q)
        assert "見つかりません" in out, f"{q!r} should not match an expert, got: {out}"
        assert "エキスパート紹介" not in out
        # The loop must read this as no-evidence, not as a usable result.
        assert not _is_substantive(out)


def test_relevant_question_still_routes():
    assert "佐藤美咲" in route_to_expert("ネットワークの構成で困っています")
    assert "エキスパート紹介" in route_to_expert("", tags=["セキュリティ"])


def test_top_performer_only_breaks_ties_among_relevant_experts():
    # 小林直樹(top) and 鈴木大輔(not top) both carry サーバー → the top performer wins.
    # The bonus must never promote a zero-relevance expert over no match at all.
    assert "小林直樹" in route_to_expert("サーバーの移行について相談")


# --- misses must be machine-detectable, not prose the loop guesses at -----------
def test_every_tool_miss_is_marked_and_non_substantive():
    """A tool that finds nothing must tag it, and the loop must see it as no-evidence.
    Guessing from Japanese prose is what let 「環境情報は未登録です」 read as grounding."""
    misses = [
        impl.query_spr(customer="D168"),                       # the original bug
        impl.score_deal_health(deal_id="D999"),
        impl.lookup_customer_environment(customer="NoSuchCo"),
        impl.route_to_expert("Where is the Otsuka Shokai office located?"),
        impl.search_products(max_price=1),
        impl.find_similar_deals_tool(customer="NoSuchCo"),
        impl.advise_solutions(customer="NoSuchCo"),
        impl.get_product_info(product="NOSUCHSKU"),
    ]
    for out in misses:
        assert is_not_found(out), f"miss not tagged: {out[:60]}"
        assert is_miss(out)
        assert not _is_substantive(out), f"miss leaked as evidence: {out[:60]}"


def test_未登録_reads_as_a_miss_not_as_evidence():
    # The one message that escaped the old prose check: it says "not registered"
    # without ever saying 見つかりません, and ありません never appears at all.
    assert is_miss("[not_found] 富士商事 の環境情報は未登録です。")
    assert not _is_substantive("[not_found] 富士商事 の環境情報は未登録です。")


def test_real_results_are_still_substantive():
    from senpai.data import store
    cust = store.all_customers()[0]["name"]
    assert _is_substantive(impl.query_spr(customer=cust))
    assert _is_substantive(impl.score_deal_health(deal_id="D001"))
    assert _is_substantive(impl.route_to_expert("ネットワークの構成で困っています"))


def test_long_report_mentioning_arimasen_is_not_a_miss():
    # 「ありません」 bounded to the opening: an analysis that merely *discusses* an
    # absence deep in its prose is real evidence, not a miss.
    report = "D016 の健全度: 62点。接触は十分だが決裁者との面談記録がありません。" + "あ" * 200
    assert not is_miss(report)
    assert _is_substantive(report)
