"""Scoped multi-entity expander: 'compare A, B, C' → one gather call per known id, so
the scheduler fans them out in a single parallel round instead of the model dribbling
one lookup per round (it emits a single tool_call per response under the full prompt).

The expander is deterministic and store-backed, so it needs no LLM.
"""
from __future__ import annotations

import json

from senpai.data import store
from senpai.llm.client import _audit_gather_calls, _multi_entity_gather_calls


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


AUDIT_MSG = """I am conducting a massive quarterly pipeline audit and need you to gather data.
1. Look up the SPR pipelines for three specific reps: 'R01', 'R05', and 'R12'.
2. Query the exact current deal status for: '富士商事', '豊田工業', and '有限会社村田印刷'.
3. Perform a semantic note search for EACH customer looking for "budget slashed" or "予算削減".
4. Find similar comparable deals for '富士商事' (in the '製造' industry) and for '豊田工業' (in the 'IT' industry).
5. Run four separate faceted searches for past deals:
   - 'サーバー' deals in '製造' that were 'won'.
   - 'ソフトウェア' deals in '飲食' that were 'lost'.
   - 'ネットワーク機器' deals in '小売' that were 'open'.
   - Any deals containing the product code 'MON27'.
6. Check our playbook for four different tactical scenarios individually:
   - Scenario 1: '決定先延ばし' (decision postponed)
   - Scenario 2: '値引き' (discounting)
   - Scenario 3: '競合優位' (competitor advantage)
   - Scenario 4: '担当者変更' (change in point of contact)
Only once you have successfully pulled all of this data from the tools, synthesize it."""


def test_quarterly_audit_prompt_fans_out_read_only_gathers():
    calls = _args(_audit_gather_calls(AUDIT_MSG))

    assert ("query_spr", {"rep_id": "R01"}) in calls
    assert ("query_spr", {"rep_id": "R05"}) in calls
    assert ("query_spr", {"rep_id": "R12"}) in calls
    assert ("query_spr", {"customer": "富士商事"}) in calls
    assert ("search_notes", {"customer": "富士商事", "query": "budget slashed OR 予算削減", "limit": 5}) in calls
    assert ("find_similar_deals", {"customer": "富士商事", "industry": "製造"}) in calls
    assert ("find_deals", {"product_category": "サーバー", "industry": "製造", "outcome": "won", "limit": 10}) in calls
    assert ("find_deals", {"product_code": "MON27", "limit": 10}) in calls
    assert ("retrieve_playbook", {"query": "決定先延ばし", "tags": ["決定先延ばし"]}) in calls
    assert ("find_deals", {"product_category": "富士商事", "limit": 10}) not in calls
    assert len(calls) >= 19
    assert len({cid for cid, _n, _a in _audit_gather_calls(AUDIT_MSG)}) == len(calls)


def test_audit_never_gathers_on_a_quoted_search_phrase():
    """Line 3 quotes the phrase to search for, on a line that also says "customer".
    Those quoted strings are not customers; gathering on them is a guaranteed
    [not_found]. Only quoted names that resolve against the store may become one."""
    customers = {a["customer"] for n, a in _args(_audit_gather_calls(AUDIT_MSG))
                 if "customer" in a}
    assert customers == {"富士商事", "豊田工業", "有限会社村田印刷"}
    assert "budget slashed" not in customers
    assert "予算削減" not in customers


def test_audit_resolves_a_quoted_alias_to_the_canonical_store_name():
    msg = AUDIT_MSG.replace("'有限会社村田印刷'", "'Murata Printing'")
    customers = {a["customer"] for n, a in _args(_audit_gather_calls(msg))
                 if "customer" in a}
    assert "有限会社村田印刷" in customers   # canonicalized, not the alias
    assert "Murata Printing" not in customers


def test_audit_drops_quoted_names_that_match_no_customer():
    msg = AUDIT_MSG.replace("'豊田工業'", "'アクメ商事'")  # not in seed
    customers = {a["customer"] for n, a in _args(_audit_gather_calls(msg))
                 if "customer" in a}
    assert "アクメ商事" not in customers
    assert "富士商事" in customers  # the real ones still gather


def test_audit_expander_stays_off_for_small_normal_prompts():
    assert _audit_gather_calls("compare R01 and R05 quickly") == []
    assert _audit_gather_calls("1. check R01\n2. answer") == []


def test_ids_adjacent_to_kana_particles_still_match():
    """Kana are Unicode word chars, so a \\b-bounded id regex silently drops "D010を".
    Japanese phrasing puts a particle straight after the last id, so the trailing
    entity of a compare turn is the one most likely to be lost."""
    deals = _valid_deals(3)
    assert len(deals) == 3
    msg = f"{deals[0]}、{deals[1]}、{deals[2]}を比較して。それぞれのヘルススコアを調べて"
    calls = _args(_multi_entity_gather_calls(msg))
    assert [a["deal_id"] for n, a in calls if n == "score_deal_health"] == deals
    assert [a["deal_id"] for n, a in calls if n == "query_spr"] == deals
    assert len(calls) == 6


def test_rep_ids_adjacent_to_kana_still_match():
    # "R05の担当案件" — no ASCII boundary after the id. The prompt must also clear the
    # expander's own guards: ≥3 numbered steps and ≥6 resulting gathers.
    calls = _args(_audit_gather_calls(
        "四半期パイプライン監査:\n"
        "1. R05の担当案件を確認\n"
        "2. R12の担当案件を確認\n"
        "3. R14の担当案件を確認\n"
        "4. 株式会社松田サービスの状況\n"
        "5. 株式会社平和システムの状況\n"
        "6. 有限会社村田印刷の状況\n"))
    assert ("query_spr", {"rep_id": "R05"}) in calls
    assert ("query_spr", {"rep_id": "R12"}) in calls
    assert ("query_spr", {"rep_id": "R14"}) in calls


def test_ascii_boundaries_still_reject_embedded_ids():
    # The lookarounds must not loosen into matching ids glued to ASCII alphanumerics.
    assert _multi_entity_gather_calls("compare XD001 and AD005") == []
