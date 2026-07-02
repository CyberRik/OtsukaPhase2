"""Chat-loop guard against the answer-as-arg leak.

Under forced tool_choice the reasoning model sometimes packs its whole final answer
(plus a stray <function=finish> tag) into a tool argument instead of finishing. That
runs a bogus query and makes the turn generate the answer twice. `_is_finish_leak`
catches it so the loop routes to a single clean synthesis instead.
"""
from __future__ import annotations

import json

from senpai.llm.client import _is_finish_leak

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
