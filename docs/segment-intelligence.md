# Segment Intelligence — GraphRAG community summarization (teaching doc)

A walkthrough of the feature we added: **what problem it solves, the theory behind
it, how it's built, and how to extend it.** Written so a new teammate can read this
once and confidently touch the code.

---

## 1. The problem, in one picture

Senpai already had three retrieval layers:

| Layer | Answers | Example |
|---|---|---|
| Hybrid semantic search (BM25 + dense) | "find notes *like* this" | "notes mentioning テレワーク" |
| Keyword knowledge RAG | "what does an approved principle say" | "how do we handle 値引き requests" |
| Graph multi-hop (`query_graph`) | **local/entity** relations | "this account's whole network" |

All three are **local** — they retrieve a handful of specific rows. None can answer a
**global / thematic** question a *manager* asks:

> 「製造業のサーバー案件、なぜ負ける？」
> "What are the common failure modes across all our lost deals?"

To answer that with plain RAG you'd have to stuff the raw daily-reports of ~100 dead
deals (tens of thousands of Japanese tokens) into the model's context at query time —
over budget on our ~11 tok/s served model, slow, and low-signal (the model loses
things in the middle of a huge prompt).

**Segment Intelligence** is the layer that answers these aggregate questions.

---

## 2. The idea: GraphRAG community summarization

This is Microsoft's **GraphRAG** pattern, adapted. The canonical recipe:

1. **Build a graph** of entities + relationships (usually via an LLM reading raw text).
2. **Partition** the graph into "communities" (clusters) with the **Leiden** algorithm.
3. **Summarize** each community once, offline, with an LLM → a "community report".
4. At query time, do a **map-reduce** over the relevant community reports instead of
   over raw documents. This is what makes *global* questions tractable.

### The key adaptation for us

Canonical GraphRAG spends most of its cost (and error budget) on **step 1** — an LLM
extracting entities/relationships from unstructured text. It hallucinates edges, and
for us it would mean ~2,337 LLM calls over our activity notes.

**We already have a clean, typed graph** (`senpai/graph/build.py`, built directly from
structured SPR data). So we **skip step 1 entirely** — no extraction, no extraction
errors, ~100× cheaper to build.

We also skip **Leiden** (step 2). Leiden is needed when you have no schema and must
*discover* structure. We *have* a schema, so our communities are **deterministic
facets**: `product_category × customer.industry`. That's more interpretable than a
Leiden blob, and on our small, hub-heavy graph Leiden tends to produce mushy clusters
anyway. (Leiden remains a future option — see §8.)

So our pipeline is really just steps **3 + 4**, which is where the value is.

---

## 3. The core design principle

> **Deterministic numbers. LLM prose. Verified prose.**

This mirrors Senpai's existing rule: *no number is ever invented by a model.*

1. **Every statistic is computed in Python** from the store + the deterministic
   deal-health engine — win rate, deal counts, top failure signals, flag tallies.
   Zero LLM involvement.
2. **The LLM writes only the narrative prose**, and only *over those pre-computed
   numbers*, offline at build time.
3. **The narrative is gated**: every numeric token in the prose must exist in the
   stats. If the model invents a figure, we throw the prose away and keep a
   deterministic templated sentence instead.

Result: the feature can *never* surface a hallucinated number, and it still ships a
useful report even with **no model available at all**.

---

## 4. Architecture / data flow

```
OFFLINE  (senpai/graph/build_communities.py — a committed build, like build_index.py)

  store.all_deals()
        │  partition by (product_category × customer.industry)
        │  thin leaves (< SEGMENT_MIN_DEALS closed) roll up to their category
        ▼
  per segment ── segment_stats() ─────────────►  DETERMINISTIC stats
     (score_deal over lost deals → failure          (win rate, counts,
      signal tallies; deal_flags; THEME_PRINCIPLES   top_failure_signals,
      → recommended play)                            recommended_principle_ids)
        │                                                   │
        │                                                   ▼
        │                                    LLM narrative (simple_complete, no_think)
        │                                    gated by ungrounded_numbers()
        │                                    └─ fails? → deterministic templated prose
        ▼
  senpai/data/index/communities.json   (committed artifact + manifest)


RUNTIME  (GPU-free)

  Manager Copilot chat
        │  LLM decides to call the tool
        ▼
  segment_intelligence(query, category, industry, outcome, limit)   [tools/impl.py]
        │
        ▼
  communities.select(...)          load committed reports (or rebuild in-memory)
        │                          pick relevant segments; broad query → category rollups
        ▼
  compact grounded string per segment (stats + narrative + CITED deal_ids)
        │  trace.record(...) for the Retrieval Explorer
        ▼
  the Assistant's existing final-synthesis round = the "reduce" → answer to the manager
```

Notice the **"reduce" is free**: we don't run a nested LLM call inside the tool. The
tool returns grounded segment reports as a string, and the chat loop's normal
synthesis round composes the final answer — exactly like every other Senpai tool.

---

## 5. The files, and why each exists

### `senpai/graph/communities.py` — the deterministic core (GPU-free)

The heart of the feature. Pure Python; no model.

- **`_outcome(rank)`** — won / lost / open, using `config.WON_RANKS` / `DEAD_RANKS`.
- **`segment_stats(deals, today)`** — iterates a segment's deals once; for each it runs
  the existing `score_deal()` and `deal_flags()`. Failure signals are tallied on
  **lost** deals (what went wrong); flags on **all** deals. Returns a plain dict of
  numbers — the *only* thing an LLM narrative may reference.
- **`_principles_for(sig_counter)`** — maps the dominant failure signal → a coaching
  theme → validated principle IDs, **reusing `senpai.coach.cases.THEME_PRINCIPLES`**
  (e.g. `missing_dm` → `no_decision_maker` → `P003`/`P006`). The "recommended play"
  is therefore grounded in human-approved knowledge, not invented.
- **`_narrative(...)`** — the deterministic templated Japanese summary. Always
  grounded (uses only numbers from the stats). This is the safety net.
- **`build_reports(today)`** — partitions everything and emits category rollups +
  thick leaves. **This is also the runtime fallback** when no committed file exists.
- **`load_reports()`** (lru-cached) / **`reload()`** — read the committed
  `communities.json` if present, else `build_reports()`. Same cache-clear discipline
  as `graph.build.reload` / `semantic.reload`.
- **`select(query, category, industry, outcome, limit)`** — picks relevant reports.
  Explicit filters win; otherwise narrow by segment names mentioned in the query; a
  genuinely broad question with no segment named falls back to **category rollups
  only**, so returned context stays bounded (this is the hierarchy paying off).
- **`format_report(r)`** — the compact grounded string the tool returns: header stats
  + narrative + dominant failure modes + recommended principle + **cited evidence
  deal IDs** (provenance).
- **`allowed_numbers(r)` / `ungrounded_numbers(text, r)`** — the grounding gate. The
  set of numbers a narrative is allowed to contain (counts, win-rate %, tallies,
  digits inside principle IDs), and the list of tokens that violate it.

### `senpai/graph/build_communities.py` — the offline build (needs the model)

Mirrors `senpai/retrieval/build_index.py`. For each report:

1. Ask the model (`simple_complete(..., no_think=True)`) for a 2–3 sentence JA summary
   over **only the stats JSON**, with hard rules ("no number not in the stats, no
   individual deal IDs, no new advice").
2. Verify with `communities.ungrounded_numbers`. Any hallucinated number → reject.
3. On any failure (bad number, empty output, **server down**) → keep the deterministic
   templated narrative. So the build is safe to run offline; worst case is a fully
   templated (but fully grounded) artifact.

Writes `communities.json` + a small `communities.manifest.json` (model, date, counts).

### `senpai/tools/impl.py` — the Copilot tool

`segment_intelligence(query, category, industry, outcome, limit)` calls
`communities.select`, records a `trace` event for the Retrieval Explorer, and returns
`format_report` joined over the matched segments. It never raises (dispatch wraps it,
but it's defensive anyway). Registered in `_DISPATCH` and given a smoke-test entry.

### `senpai/tools/schemas.py` — the tool contract

The JSON schema (params: `query` required, plus `category` / `industry` / `outcome` /
`limit`), added to **`MANAGER_TOOLS`** and **`RESEARCH_TOOLS`**. The description is
written so the model reaches for it on aggregate/thematic questions.

### `senpai/llm/routing.py` — reasoning routing

Added to **`HIGH_REASONING_TOOLS`**: cross-segment sensemaking is genuine synthesis,
so the final answer round should reason rather than just restate.

### `senpai/config.py` — knobs

- `COMMUNITIES_PATH` — where the committed artifact lives (`data/index/communities.json`).
- `SEGMENT_MIN_DEALS` (default 5) — a leaf needs this many **closed** deals to be
  emitted on its own; thinner leaves are represented by their category rollup.

### `tests/test_communities.py` — the guarantees

7 tests, no GPU/model needed. Notably:
- **Partition completeness** — category rollups account for every deal.
- **Hand-count parity** — a category's win rate/counts match a straight recount off the
  store (proves the numbers are real aggregates).
- **Grounding invariant** — `ungrounded_numbers(narrative) == []` for every report.
  This is the single most important test: it's the machine-checkable version of "no
  invented numbers."

---

## 6. How to run it

```bash
export SENPAI_TODAY=2026-06-16                 # pin scoring's "today" to the seed anchor

# See the deterministic reports (no model needed):
.venv/bin/python -m senpai.graph.communities

# Tests (no model needed):
.venv/bin/pytest tests/test_communities.py -q

# Build the committed artifact WITH LLM narratives (needs the served model up):
.venv/bin/python -m senpai.graph.build_communities   # writes index/communities.json

# End-to-end: in the Manager Copilot, ask 「製造業のサーバー案件、なぜ負けやすい？」
#   → the model calls segment_intelligence → grounded answer with cited deal IDs.
```

Sample output today:

```
■ サーバー（カテゴリ全体） — 案件27件／成約15・失注7・進行中5／勝率68%
【サーバー（カテゴリ全体）】案件27件（成約15・失注7、勝率68%）。失注の主因は「接触の停滞」（7件）。推奨原則: P001。
失注の主な要因: 接触の停滞(7件)、ランク滞留(7件)、ランク低下(7件)、日報の停滞サイン(1件)
推奨原則: P001
根拠案件: D067, D072, D088, D115, D130, D163, D210, D233
```

---

## 7. Why it's built this way — design notes

- **Committed artifact, GPU-free runtime.** Same philosophy as `build_index.py`: the
  expensive summarization happens once, offline, and is committed. The query path just
  loads JSON. If the file is missing, `build_reports()` rebuilds deterministically
  in-memory — so the runtime *never* hard-depends on the model.
- **Reduce for free.** The tool returns retrieval results (grounded segment reports),
  and the chat loop's existing synthesis round does the map-reduce "reduce." No nested
  LLM call inside a tool = simpler, faster, and it reuses the reasoning router.
- **Hierarchy bounds context.** A broad question returns ~7 category rollups, not 37
  leaves — the mechanism that keeps a "global" answer within the model's context.
- **Heavy reuse.** `store` accessors, `score_deal`/`deal_flags`, `THEME_PRINCIPLES`,
  the `_INVENTED`-style grounding gate, `simple_complete`, the `build_index` artifact
  pattern, `trace.record`, and the tool dispatch/role-subset machinery are all
  existing utilities — the new code is mostly *composition*.

---

## 8. Known limits & future work

- **Correlated failure signals.** On the current seed, lost deals tend to fire
  `staleness` / `rank_age` / `rank_regression` together, so they tie in the tallies and
  `missing_dm` rarely tops the list. That's a data characteristic, not a bug; if we
  want more discriminating "failure modes" we can weight or de-correlate signals.
- **Thin leaves.** Many `category × industry` leaves are small; the
  `SEGMENT_MIN_DEALS` threshold + category rollup handles this, but very granular
  questions fall back to the category level.
- **Phase 4 ideas:** trend diffing across nightly builds ("failure mode X rising in
  ネットワーク機器 this quarter"), a Leiden partition as an alternative axis, and an
  optional `/manager/segments` browsable UI page (currently Copilot-tool-only).

---

## 9. TL;DR

We added the **global sensemaking** retrieval layer. It partitions deals into
category×industry communities, precomputes a **grounded** report per community offline
(deterministic numbers, LLM prose verified against those numbers, committed like the
vector index), and exposes a `segment_intelligence` Copilot tool that selects the
relevant reports while the chat loop does the reduce. It answers the aggregate
questions a manager actually asks — and it structurally cannot invent a number.
