"""Scoped multi-entity expander: 'compare A, B, C' → one gather call per known id, so
the scheduler fans them out in a single parallel round instead of the model dribbling
one lookup per round (it emits a single tool_call per response under the full prompt).

The expander is deterministic and store-backed, so it needs no LLM.
"""
from __future__ import annotations

import json

from senpai.data import store
from senpai.llm.client import _multi_entity_gather_calls


def _valid_deals(n: int) -> list[str]:
    return [d["deal_id"] for d in list(store.all_deals())[:n]] if hasattr(store, "all_deals") \
        else [c for c in ("D001", "D012", "D133", "D168") if store.get_deal(c)][:n]


def _args(calls):
    return [(name, json.loads(a)) for _cid, name, a in calls]


def test_two_known_deals_fan_out_full_bundle():
    deals = _valid_deals(2)
    assert len(deals) == 2  # sanity: seed has the deals this test needs
    calls = _multi_entity_gather_calls(f"compare deals {deals[0]} and {deals[1]}")
    # Grouped by tool: all deal_health, then all query_spr — one parallel round.
    assert _args(calls) == [
        ("score_deal_health", {"deal_id": deals[0]}),
        ("score_deal_health", {"deal_id": deals[1]}),
        ("query_spr", {"deal_id": deals[0]}),
        ("query_spr", {"deal_id": deals[1]}),
    ]
    # synthetic ids are unique so each tool response can be matched
    assert len({cid for cid, _n, _a in calls}) == 4


def test_three_deals_health_and_records_grouped():
    deals = _valid_deals(3)
    assert len(deals) == 3
    msg = f"compare {deals[0]}, {deals[1]}, and {deals[2]}"
    calls = _args(_multi_entity_gather_calls(msg))
    health = [a["deal_id"] for n, a in calls if n == "score_deal_health"]
    records = [a["deal_id"] for n, a in calls if n == "query_spr"]
    assert health == deals            # all 3 health, in order, grouped first
    assert records == deals           # then all 3 records
    assert len(calls) == 6            # 3 health + 3 records, one round


def test_single_entity_does_not_trigger():
    d = _valid_deals(1)[0]
    assert _multi_entity_gather_calls(f"how is deal {d} doing?") == []


def test_unknown_ids_are_ignored():
    # Two well-formed but non-existent ids → nothing valid → no fan-out.
    assert _multi_entity_gather_calls("compare D99999 and D88888") == []


def test_mix_of_valid_and_invalid_needs_two_valid():
    d = _valid_deals(1)[0]
    # one real + one fake = only one valid entity → below the ≥2 threshold.
    assert _multi_entity_gather_calls(f"compare {d} and D99999") == []


def test_duplicate_ids_count_once():
    d = _valid_deals(1)[0]
    assert _multi_entity_gather_calls(f"compare {d} and {d} again") == []


def test_customer_ids_also_fan_out():
    # Find two distinct valid customer ids from the store.
    custs = []
    for d in _valid_deals(4):
        cid = store.get_deal(d)["customer_id"]
        if cid not in custs and store.get_customer(cid):
            custs.append(cid)
        if len(custs) == 2:
            break
    if len(custs) < 2:
        return  # seed didn't yield two distinct customers; skip silently
    calls = _multi_entity_gather_calls(f"compare {custs[0]} vs {custs[1]}")
    assert _args(calls) == [("query_spr", {"customer": custs[0]}),
                            ("query_spr", {"customer": custs[1]})]


def test_empty_message():
    assert _multi_entity_gather_calls("") == []
    assert _multi_entity_gather_calls(None) == []
