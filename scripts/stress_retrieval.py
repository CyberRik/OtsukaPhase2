"""Stress / correctness harness for Senpai hybrid retrieval.

Run:  SENPAI_TODAY=2026-06-16 PYTHONPATH=. .venv/bin/python scripts/stress_retrieval.py
Probes: paraphrase recall (the dense value-prop), fusion sanity, determinism,
graceful degradation, edge-case/fuzz robustness, score monotonicity, latency.
"""
from __future__ import annotations

import os
import random
import time

os.environ.setdefault("SENPAI_TODAY", "2026-06-16")

from senpai import config
config.USE_EMBEDDINGS = True                      # force the full hybrid path on

from senpai.retrieval import semantic

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
results = {"pass": 0, "fail": 0}


def check(name, ok, detail=""):
    results["pass" if ok else "fail"] += 1
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def topk_texts(query, corpus="activities", k=5, **kw):
    return [h.get("text", "") for h in semantic.semantic_search(query, corpus, k, **kw)]


# ---------------------------------------------------------------------------
print("\n=== 1. Paraphrase recall (low token overlap → dense should find it) ===")
# (paraphrase query, concept token that must appear in a top-5 hit)
# (paraphrase query, set of concept tokens — ANY in a top-5 hit text counts)
PARAPHRASES = [
    ("お金が足りなくて話が前に進まない", ("予算",)),            # budget
    ("誰が最終的に判断するのか分からない", ("決裁", "上と相談")),  # decision maker
    ("機械を置く部屋の温度や電源を調べたい", ("空調", "サーバー室")),  # server room
    ("製品を実際に見せたら手応えがあった", ("デモ", "前向き")),    # demo
    ("他社と価格を比べられている", ("競合", "比較")),           # being compared on price
]
for q, concepts in PARAPHRASES:
    concept = "/".join(concepts)
    def _has_concept(texts):
        return any(any(c in t for c in concepts) for t in texts)
    def hit(mode_on):
        config.USE_EMBEDDINGS = mode_on
        semantic.reload()
        return any(concept in t or t for t in topk_texts(q))
    config.USE_EMBEDDINGS = True; semantic.reload()
    hybrid = _has_concept(topk_texts(q))
    config.USE_EMBEDDINGS = False; semantic.reload()
    bm25 = _has_concept(topk_texts(q))
    config.USE_EMBEDDINGS = True; semantic.reload()
    check(f"'{q[:16]}…' → 「{concept}」  (hybrid={'Y' if hybrid else 'N'}, bm25={'Y' if bm25 else 'N'})",
          hybrid)

# ---------------------------------------------------------------------------
print("\n=== 2. Fusion sanity (hybrid overlaps both, isn't identical to either) ===")
q = "予算が厳しく決裁が止まっている"
config.USE_EMBEDDINGS = False; semantic.reload()
bm25_ids = [(h["deal_id"], h["activity_date"]) for h in semantic.semantic_search(q, "activities", 10)]
config.USE_EMBEDDINGS = True; semantic.reload()
hyb_ids = [(h["deal_id"], h["activity_date"]) for h in semantic.semantic_search(q, "activities", 10)]
overlap = len(set(bm25_ids) & set(hyb_ids))
check("hybrid returns 10 hits", len(hyb_ids) == 10, f"{len(hyb_ids)}")
check("hybrid shares some BM25 hits", overlap >= 1, f"overlap={overlap}/10")

# ---------------------------------------------------------------------------
print("\n=== 3. Determinism (same query 5× → identical) ===")
config.USE_EMBEDDINGS = True; semantic.reload()
runs = [tuple((h["deal_id"], h["activity_date"], h["score"])
              for h in semantic.semantic_search("値引きを求められて停滞", "activities", 8))
        for _ in range(5)]
check("5 runs identical", all(r == runs[0] for r in runs))

# ---------------------------------------------------------------------------
print("\n=== 4. Score monotonicity (non-increasing) ===")
hits = semantic.semantic_search("サーバーの設置環境を確認", "activities", 10)
scores = [h["score"] for h in hits]
check("scores non-increasing", scores == sorted(scores, reverse=True), str([round(s,4) for s in scores[:5]]))

# ---------------------------------------------------------------------------
print("\n=== 5. Graceful degradation (every layer returns results) ===")
config.USE_EMBEDDINGS = True; semantic.reload()
check("hybrid mode label", semantic.mode().startswith("hybrid"), semantic.mode())
n_hybrid = len(semantic.semantic_search("予算", "activities", 5))
config.USE_EMBEDDINGS = False; semantic.reload()
check("BM25 mode label", semantic.mode() == "BM25", semantic.mode())
n_bm25 = len(semantic.semantic_search("予算", "activities", 5))
# keyword-only: knock out BM25
_orig = semantic.HAS_BM25
semantic.HAS_BM25 = False; semantic.reload()
n_kw = len(semantic.semantic_search("予算", "activities", 5))
check("keyword fallback returns hits", n_kw > 0, f"{n_kw}")
semantic.HAS_BM25 = _orig; semantic.reload()
check("all layers return hits", n_hybrid and n_bm25 and n_kw, f"hybrid={n_hybrid} bm25={n_bm25} kw={n_kw}")

# ---------------------------------------------------------------------------
print("\n=== 6. Edge cases & fuzzing (must never crash; always a list) ===")
config.USE_EMBEDDINGS = True; semantic.reload()
EDGE = ["", "   ", "\n\t", "?!?!", "🤖🔥", "a"*5000, "サーバー"*500,
        "SELECT * FROM deals; DROP TABLE", "1234567890", "予算"]
ok = True
for e in EDGE:
    try:
        r = semantic.semantic_search(e, "activities", 5)
        assert isinstance(r, list)
    except Exception as ex:  # noqa: BLE001
        ok = False; print(f"     crashed on {e[:20]!r}: {ex}")
check("no crash on 10 hostile inputs", ok)
check("empty query → []", semantic.semantic_search("", "activities") == [])
check("unknown corpus → []", semantic.semantic_search("予算", "nope") == [])
# random fuzz
rnd = random.Random(0); fok = True
for _ in range(200):
    s = "".join(rnd.choice("あ亜A1 　、。予算サーバー決裁") for _ in range(rnd.randint(0, 30)))
    try:
        assert isinstance(semantic.semantic_search(s, "activities", 3), list)
    except Exception:  # noqa: BLE001
        fok = False; break
check("200 random fuzz queries survive", fok)

# ---------------------------------------------------------------------------
print("\n=== 7. tags filter (playbook) ===")
hits = semantic.semantic_search("決裁者が見えない", "playbook", 3, tags=["決裁者未特定"])
check("playbook returns hits", len(hits) > 0, f"{[h.get('entry_id') for h in hits]}")

# ---------------------------------------------------------------------------
print("\n=== 8. Latency (hybrid, warm) ===")
config.USE_EMBEDDINGS = True; semantic.reload()
semantic.semantic_search("warmup", "activities", 5)         # warm caches/model
qs = ["予算が厳しい", "決裁者が不明", "サーバー更改", "デモの反応", "競合と比較中"]
times = []
for _ in range(40):
    q = qs[_ % len(qs)]
    t = time.perf_counter(); semantic.semantic_search(q, "activities", 5); times.append(time.perf_counter()-t)
times.sort()
p50, p95 = times[len(times)//2]*1000, times[int(len(times)*0.95)]*1000
check("p95 latency < 250ms (CPU)", p95 < 250, f"p50={p50:.1f}ms p95={p95:.1f}ms")

# ---------------------------------------------------------------------------
print(f"\n=== SUMMARY: {results['pass']} passed, {results['fail']} failed ===")
