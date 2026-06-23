"""Tests that the enriched seed actually *demonstrates* the coaching engine.

The pre-enrichment seed had 28-char reports (every lens fired) and 100%-filled
challenges (several issue rules never fired). These assert the enrichment fixed
that — a realistic report-quality spread and the dormant rules now firing — while
keeping the SPR tables byte-stable and the demo anchors intact.
"""
from __future__ import annotations

from collections import Counter

from senpai import config
from senpai.coach.review import LENSES, _present
from senpai.data import gen_seed, store


def _lenses_fired(text: str) -> int:
    return sum(1 for L in LENSES if not _present(text, L.cues))


def test_report_quality_has_a_real_spread():
    reports = [a["daily_report"] for a in store.all_activities() if a.get("daily_report")]
    dist = Counter(_lenses_fired(t) for t in reports)
    thorough = sum(dist[k] for k in (0, 1))
    thin = sum(dist[k] for k in (3, 4, 5))
    # both ends must exist — thorough notes (coach stays quiet) AND thin ones (signal)
    assert thorough > 0.3 * len(reports), "too few thorough reports — coach looks gimmicky"
    assert thin > 0, "no thin reports — nothing for the coach to flag"


def test_weak_customer_discovery_can_now_fire():
    # challenge fill must no longer be 100%, so the discovery rule can trigger
    acts = store.all_activities()
    filled = sum(1 for a in acts if a.get("customer_challenge"))
    assert filled < len(acts), "customer_challenge is 100% filled — discovery rule can't fire"


def test_coaching_threads_are_grounded():
    threads = store.all_coaching_threads()
    assert threads, "no coaching threads generated"
    deal_ids = {d["deal_id"] for d in store.all_deals()}
    rep_ids = {r["employee_id"] for r in store.all_reps()}
    valid_issue = set(gen_seed._THREAD_TEXT)
    valid_status = {"open", "acknowledged", "resolved"}
    for t in threads:
        assert t["deal_id"] in deal_ids
        assert t["employee_id"] in rep_ids and t["manager_id"] in rep_ids
        assert t["issue_key"] in valid_issue
        assert t["status"] in valid_status
        assert t["messages"] and all(m["text"] for m in t["messages"])


def test_seed_is_deterministic():
    a = gen_seed.generate()
    b = gen_seed.generate()
    for table in ("sales_activities", "coaching_threads", "deals"):
        assert a[table] == b[table], f"{table} not byte-stable across regen"


def test_demo_anchors_intact():
    # the report enrichment must not have moved the load-bearing anchors
    assert store.customer_name(store.get_deal("D001")["customer_id"]) == "有限会社村田印刷"
    assert store.get_rep("R05") and store.get_rep("R05")["name"] == "伊藤翔"
    assert len(store.all_deals()) == 520
    assert len(store.all_activities()) == 2337
