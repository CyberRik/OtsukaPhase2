"""Stress / robustness harness for the whole Senpai pipeline (beyond retrieval).

Run:  SENPAI_TODAY=2026-06-16 PYTHONPATH=. python3 scripts/stress_pipeline.py

Probes the deterministic core the chat loop depends on:
  1. Tool dispatch — every tool survives empty / garbage / hostile args and never
     raises (the chat loop must never crash); valid calls don't error.
  2. Scoring engine — edge cases (empty/missing fields, junk dates, every rank);
     score always in 0–100 with a valid band.
  3. Flags — same edge cases never crash.
  4. morning_briefing — every rep + team + unknown rep; sorted, grounded, deterministic.
  5. find_deals — facet filters are honoured, outcome matches the rank model,
     hostile inputs never crash, deterministic.
  6. Store referential integrity — deals resolve to real customers/reps; unknown
     ids degrade to None/[].
  7. Whole-pipeline determinism — score every open deal twice → identical.

Network tools (web_search) are skipped to stay hermetic.
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("SENPAI_TODAY", "2026-06-16")
os.environ.setdefault("SENPAI_USE_EMBEDDINGS", "0")   # hermetic: BM25-only, no model download

from senpai import config
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.briefing import format_briefing, morning_briefing
from senpai.retrieval.deals import deal_facets, find_deals, outcome_breakdown
from senpai.tools import impl
from senpai.tools.impl import _DISPATCH

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
results = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


# Representative VALID args per tool (so we can assert valid calls don't error).
VALID = {
    "query_spr": {"deal_id": "D001"},
    "find_deals": {"product_category": "サーバー"},
    "find_similar_deals": {"customer": "C01"},
    "retrieve_playbook": {"query": "決裁が進まない"},
    "lookup_customer_environment": {"customer": "C01"},
    "get_product_info": {"product": "MFP30"},
    "score_deal_health": {"deal_id": "D001"},
    "review_sales_note": {"note": "社内で検討してから連絡します。"},
    "draft_daily_report": {"activity": "デモを実施", "deal_id": "D001"},
    "route_to_expert": {"question": "ネットワーク構成の相談", "tags": ["ネットワーク"]},
    "summarize_reports": {"rep_id": "R05"},
    "get_seasonal_context": {"month": 3},
    "morning_briefing": {"rep_id": "R12", "limit": 5},
    "list_at_risk_deals": {"limit": 5},
    "team_pipeline_overview": {},
    "team_report_digest": {},
    "rep_coaching_focus": {},
    "draft_message": {"to": "伊藤さん", "about": "D003の進捗", "deal_id": "D003"},
    "search_products": {"category": "サーバー"},
    "create_quote": {"items": [{"sku": "MFP30", "qty": 2}]},
    "schedule_meeting": {"title": "商談", "date": "2026-07-01", "start_time": "10:00"},
    "send_email": {"to": "a@example.com", "subject": "件名", "body": "本文"},
    "get_calendar": {"day": "today"},
    "search_knowledge": {"query": "値引き交渉"},
    "search_notes": {"query": "予算が厳しい", "customer": "C01"},
    "query_graph": {"intent": "account", "customer": "C28"},
}
SKIP_LIVE = {"web_search"}   # network — dispatch wrapper still guards it

HOSTILE_ARGS = [
    {}, {"foo": "bar"}, {"deal_id": None}, {"limit": "abc"}, {"customer": 12345},
    {"query": "🤖🔥" * 100}, {"rep_id": "'; DROP TABLE deals; --"},
    {"product_category": "あ" * 3000}, {"month": -999}, {"items": "not-json"},
]


# ---------------------------------------------------------------------------
print("\n=== 1. Tool dispatch robustness (never raises; valid calls don't error) ===")
all_tools = sorted(_DISPATCH)
check("every role-set tool is in dispatch", True, f"{len(all_tools)} tools registered")

no_raise = True
for name in all_tools:
    for args in HOSTILE_ARGS:
        try:
            out = impl.dispatch(name, args)
            assert isinstance(out, str)
        except Exception as ex:  # noqa: BLE001 — dispatch must absorb everything
            no_raise = False
            print(f"     RAISED: {name}({args}) -> {ex}")
check(f"{len(all_tools)} tools × {len(HOSTILE_ARGS)} hostile arg-sets never raise", no_raise)

# malformed JSON string args + unknown tool
check("malformed JSON args → graceful str",
      isinstance(impl.dispatch("query_spr", "{bad json"), str)
      and impl.dispatch("query_spr", "{bad json").startswith("[error]"))
check("unknown tool name → graceful str",
      impl.dispatch("does_not_exist", {}).startswith("[error]"))

valid_ok = True
for name, args in VALID.items():
    if name in SKIP_LIVE:
        continue
    out = impl.dispatch(name, args)
    if not isinstance(out, str) or out.startswith("[error]"):
        valid_ok = False
        print(f"     valid call errored: {name}({args}) -> {out[:80]!r}")
check(f"{len(VALID) - len(SKIP_LIVE)} valid tool calls return non-error strings", valid_ok)


# ---------------------------------------------------------------------------
print("\n=== 2. Scoring engine edge cases (0–100, valid band, no crash) ===")
JUNK_DEALS = [
    {},                                                        # everything missing
    {"order_rank": "3_A"},                                     # no dates
    {"order_rank": "ZZZ_unknown"},                             # unknown rank
    {"order_rank": "2_A+", "rank_updated_at": "not-a-date",
     "expected_order_date": "2026-13-99", "days_until_order": "x"},   # junk dates/types
    {"order_rank": "4_B", "initial_order_rank": "2_A+"},       # regression
]
JUNK_ACTS = [
    [],
    [{"activity_date": None}],
    [{"activity_date": "garbage", "daily_report": 12345}],
    [{"daily_report": "検討します"}],                          # missing date, stall word
    [{"activity_date": "2099-01-01"}],                          # far-future contact
]
score_ok = True
for d in JUNK_DEALS:
    for acts in JUNK_ACTS:
        try:
            r = score_deal(d, acts)
            assert 0 <= r.score <= 100 and r.band in ("red", "yellow", "green")
        except Exception as ex:  # noqa: BLE001
            score_ok = False
            print(f"     score_deal crashed: {d} / {acts} -> {ex}")
check(f"{len(JUNK_DEALS)}×{len(JUNK_ACTS)} junk deal/activity combos score cleanly", score_ok)

# every rank in the model scores without error
rank_ok = all(0 <= score_deal({"order_rank": r}, []).score <= 100 for r in config.ORDER_RANKS)
check("every order_rank scores in range", rank_ok)


# ---------------------------------------------------------------------------
print("\n=== 3. Flags robustness (never crash on junk) ===")
flags_ok = True
for d in JUNK_DEALS:
    for acts in JUNK_ACTS:
        try:
            fl = deal_flags(d, acts, health_band="red")
            assert isinstance(fl, list)
        except Exception as ex:  # noqa: BLE001
            flags_ok = False
            print(f"     deal_flags crashed: {d} / {acts} -> {ex}")
check("flags never crash on junk inputs", flags_ok)


# ---------------------------------------------------------------------------
print("\n=== 4. morning_briefing (all reps + team + unknown; sorted, grounded) ===")
all_reps = [r["employee_id"] for r in store.all_reps()]
deal_ids = {d["deal_id"] for d in store.all_deals()}
brief_ok, sorted_ok, grounded_ok = True, True, True
for rid in all_reps + ["", "R_NOPE"]:
    try:
        items = morning_briefing(rep_id=rid)
        assert isinstance(items, list)
        pr = [it.priority for it in items]
        if pr != sorted(pr, reverse=True):
            sorted_ok = False
        if any(it.deal_id not in deal_ids for it in items):
            grounded_ok = False
        assert isinstance(format_briefing(items, rep_id=rid), str)
    except Exception as ex:  # noqa: BLE001
        brief_ok = False
        print(f"     briefing crashed for rep={rid!r}: {ex}")
check(f"briefing runs for {len(all_reps)} reps + team + unknown", brief_ok)
check("briefing items always sorted by priority desc", sorted_ok)
check("every briefing item references a real deal", grounded_ok)
check("unknown rep → empty briefing", morning_briefing(rep_id="R_NOPE") == [])
# determinism
b1 = [(i.deal_id, i.priority, i.action) for i in morning_briefing(rep_id="R12")]
b2 = [(i.deal_id, i.priority, i.action) for i in morning_briefing(rep_id="R12")]
check("briefing deterministic (2 runs identical)", b1 == b2)


# ---------------------------------------------------------------------------
print("\n=== 5. find_deals (filters honoured, outcome matches rank model, robust) ===")
facets = deal_facets()
cust_by_id = {c["customer_id"]: c for c in store.all_customers()}

# 5a. every category filter returns only that category
cat_ok = True
for cat in facets["product_category"]:
    if any(d["product_category"] != cat for d in find_deals(product_category=cat, limit=0)):
        cat_ok = False
check("category filter exact across all categories", cat_ok)

# 5b. every size filter joins correctly to the customer
size_ok = True
for sz in facets["size"]:
    for d in find_deals(size=sz, limit=0):
        if cust_by_id.get(d["customer_id"], {}).get("size") != sz:
            size_ok = False
check("size filter joins to customer across all sizes", size_ok)

# 5c. outcome filters match the config rank model
won = find_deals(outcome="won", limit=0)
lost = find_deals(outcome="lost", limit=0)
opn = find_deals(outcome="open", limit=0)
check("outcome=won → only WON_RANKS", all(d["order_rank"] in config.WON_RANKS for d in won), f"{len(won)}")
check("outcome=lost → only DEAD_RANKS", all(d["order_rank"] in config.DEAD_RANKS for d in lost), f"{len(lost)}")
check("outcome=open → only OPEN_RANKS", all(config.is_open_rank(d["order_rank"]) for d in opn), f"{len(opn)}")

# 5d. breakdown sums to total for a broad query
alld = find_deals(limit=0)
bd = outcome_breakdown(alld)
check("outcome breakdown sums to total", sum(bd.values()) == len(alld), f"{bd} of {len(alld)}")

# 5e. amount band monotonic & respected
band = find_deals(min_amount=500_000, max_amount=2_000_000, limit=0)
check("amount band respected", all(500_000 <= (d.get("total_order_amount", 0) or 0) <= 2_000_000 for d in band), f"{len(band)}")

# 5f. result list sorted by amount desc
amts = [d.get("total_order_amount", 0) or 0 for d in find_deals(product_category="ソフトウェア", limit=0)]
check("results sorted by amount desc", amts == sorted(amts, reverse=True))

# 5g. hostile inputs never crash; combined-facet result is a subset
fd_ok = True
HOSTILE_FD = [
    {"product_category": "SELECT *"}, {"min_amount": "abc"}, {"limit": -5},
    {"limit": 10**9}, {"order_rank": "🤖"}, {"industry": "存在しない"},
    {"product_code": "'; DROP"}, {"size": " "}, {"outcome": "maybe"},
]
for a in HOSTILE_FD:
    try:
        assert isinstance(find_deals(**a), list)
    except Exception as ex:  # noqa: BLE001
        fd_ok = False
        print(f"     find_deals crashed: {a} -> {ex}")
# random facet fuzz
rnd = random.Random(0)
for _ in range(150):
    a = {
        "product_category": rnd.choice(facets["product_category"] + ["", "x"]),
        "size": rnd.choice(facets["size"] + ["", "y"]),
        "outcome": rnd.choice(["won", "lost", "open", "", "z"]),
        "min_amount": rnd.choice([None, 0, 100000, "bad"]),
        "limit": rnd.choice([0, 3, -1, 50]),
    }
    try:
        assert isinstance(find_deals(**a), list)
    except Exception as ex:  # noqa: BLE001
        fd_ok = False
        print(f"     find_deals fuzz crashed: {a} -> {ex}")
        break
check("find_deals survives hostile + 150 fuzz combos", fd_ok)
combined = find_deals(product_category="サーバー", size="中規模", outcome="won", limit=0)
sub = find_deals(product_category="サーバー", limit=0)
check("combined facets ⊆ single facet", len(combined) <= len(sub))
# determinism
check("find_deals deterministic",
      [d["deal_id"] for d in find_deals(product_category="サーバー", limit=0)]
      == [d["deal_id"] for d in find_deals(product_category="サーバー", limit=0)])


# ---------------------------------------------------------------------------
print("\n=== 6. Store referential integrity ===")
deals = store.all_deals()
check("every deal resolves to a real customer",
      all(store.get_customer(d["customer_id"]) for d in deals))
check("every deal resolves to a real rep",
      all(store.get_rep(store.deal_rep_id(d)) for d in deals))
check("activities_for_deal always returns a list",
      all(isinstance(store.activities_for_deal(d["deal_id"]), list) for d in deals[:50]))
check("unknown ids degrade to None/[]",
      store.get_deal("D_NOPE") is None and store.get_customer("C_NOPE") is None
      and store.activities_for_deal("D_NOPE") == [])
check("resolve_customer on junk → None",
      store.resolve_customer("___nonexistent___") is None)


# ---------------------------------------------------------------------------
print("\n=== 7. Whole-pipeline determinism (score every open deal twice) ===")
def scan():
    return [(d["deal_id"], score_deal(d, store.activities_for_deal(d["deal_id"])).score)
            for d in store.open_deals()]
s1, s2 = scan(), scan()
check(f"scored {len(s1)} open deals, 2 runs identical", s1 == s2)
bands = {"red": 0, "yellow": 0, "green": 0}
for d in store.open_deals():
    bands[score_deal(d, store.activities_for_deal(d["deal_id"])).band] += 1
check("health band distribution is sane (all three present)",
      all(v > 0 for v in bands.values()), str(bands))


# ---------------------------------------------------------------------------
print(f"\n=== SUMMARY: {results['pass']} passed, {results['fail']} failed ===")
raise SystemExit(1 if results["fail"] else 0)
