# Senpai — Task Checklist

> Living tracker for the Senpai deal-health copilot. Check items off as they land;
> add new features/ideas under **Backlog** and promote them to **In progress** when started.
> Keep this honest — only tick a box when it's actually done and verified.
>
> Last updated: 2026-06-23 (added morning briefing; logged sales-assist feature backlog)

---

## ✅ Done

### Data
- [x] Generate large multi-year synthetic dataset in the real SPR schema (150 customers,
      520 deals, FY2023–2026) for demo/training. Regen via `senpai/data/gen_seed.py`.
- [x] Preserve test/demo anchors (D001/村田印刷, C28/松田, R05/伊藤翔, Aozora-unique /
      Yamato-ambiguous aliases).
- [x] Keep seed JSON byte-stable & committed; `_fy()` Japanese fiscal-year helper.
- [x] Move `rank_history` out of `Schema.md` into a separate supplementary file
      (Schema.md reverted to ground truth).

### Hybrid retrieval (Phase 1)
- [x] `senpai/retrieval/semantic.py` — BM25 (rank_bm25) + dense embeddings (fastembed/ONNX, CPU)
      fused via Reciprocal Rank Fusion (RRF).
- [x] Japanese tokenization: Janome with POS filtering + stopword/suffix/lone-hiragana removal.
- [x] `senpai/retrieval/build_index.py` — precompute + commit corpus vectors
      (`data/index/*.npy/.meta.json/.tokens.json/manifest.json`), byte-stable.
- [x] Optional-with-fallback: dense → BM25 → keyword degrade (mirrors `SENPAI_USE_LLM`).
- [x] New `search_notes` tool wired into `tools/impl.py` + `schemas.py` + role sets.
- [x] `retrieve_playbook` upgraded to rank via semantic internally (same signature/return).
- [x] Retrieval config in `config.py` (`EMBED_MODEL`, `RRF_K`, `BM25_WEIGHT`, `DENSE_WEIGHT`, …).
- [x] Stress harness `scripts/stress_retrieval.py` (19/19 checks passing); fixed 3 fusion bugs
      (duplicate flooding, zero-score BM25 noise, JA function-word pollution).
- [x] Tests `tests/test_semantic.py` (hermetic BM25 default; dense gated by `SENPAI_TEST_DENSE`).

### Knowledge graph (Phase 2)
- [x] `senpai/graph/build.py` — networkx MultiDiGraph (customer→deal→activity→rep→product),
      built from the store at runtime.
- [x] `senpai/graph/query.py` — `reps_who_win` / `account_graph` / `connections` / `similar_by_graph`.
- [x] New `query_graph` tool wired into tools + role sets.
- [x] Tests `tests/test_graph.py`.

### Multimodal ingestion (prototype)
- [x] Review/verify the standalone ingestion prototype (`senpai/ingestion/multimodal.py`).
- [x] Wire it to Groq's free tier (Whisper STT + vision OCR + LLM structuring → pydantic
      `ActivityExtraction`).
- [x] Ingestion config in `config.py` (`INGEST_*`, `have_multimodal()`); load both repo-root
      `.env` and `senpai/.env`.
- [x] Verified end-to-end on Groq (real text structuring + real image OCR); 76 tests still pass.
- [x] Integration brief `docs/ingestion_integration_prompt.md` for wiring ingestion into the
      main pipeline later.

### Sales-assist features
- [x] **Morning briefing / next-best-action** (`senpai/briefing.py`) — per-rep (or team)
      prioritized worklist: open deals ranked by urgency × value, one concrete next action each,
      plus a predictive cadence nudge before a deal goes yellow. Exposed as the `morning_briefing`
      tool (junior + manager role sets); tests in `tests/test_briefing.py`.
- [x] **Faceted deal search** (`senpai/retrieval/deals.py`) — grounded structured search over the
      real SPR fields (deal product_category / order_rank / amount / product code, customer
      industry / size / profile_tags); outcome (won/lost/open) derived from the config rank model.
      Reports the win/lost/open breakdown of matches; no-match returns the actual valid facet
      values (from `deal_facets()`) instead of inventing data. Exposed as the `find_deals` tool
      (junior + manager + research role sets); tests in `tests/test_deals_search.py`.

### Robustness / testing
- [x] **Pipeline stress harness** (`scripts/stress_pipeline.py`, 31 checks) — hammers tool
      dispatch (27 tools × hostile args), the scoring engine + flags (junk fields/dates/types),
      `morning_briefing`, `find_deals` (facets + fuzz), store referential integrity, and
      whole-pipeline determinism. Complements `scripts/stress_retrieval.py` (19 checks).
- [x] Fixed 2 engine robustness bugs the harness caught: `score_deal`/`deal_flags` crashed on a
      non-int `days_until_order` and a non-str `daily_report`/`business_card_info`. Added `_int()`
      coercion + str-coercion so malformed rows (e.g. LLM-ingested) degrade instead of raising.
- [x] **De-correlated scoring double-count** — `staleness` and `low_activity` both fired on the
      same silence (e.g. +40 pts from one cold streak). `low_activity` now only fires when
      `staleness` didn't (i.e. no logged activity at all). Tests updated.
- [x] **Health backtest / calibration harness** (`scripts/backtest_health.py`) — scores closed
      deals, reports won-vs-lost separation, AUC, and loss-rate calibration by band/score-bucket.
      Runs on synthetic data now (internal-consistency check, with leakage caveat); ready to point
      at real snapshot-before-close history to calibrate weights/cutoffs for production.

### Docs
- [x] `docs/retrieval.md`, `docs/synthetic_dataset.md`, updated `senpai/README.md`.

---

## 🔜 To do — multimodal ingestion integration
> Tracked in detail in `docs/ingestion_integration_prompt.md`. Deferred by user until §7 filled in.

- [ ] Consolidate to ONE ingestion module; delete `pipeline.py` + duplicate `ActivityExtraction`.
- [ ] Add a real persistence path: `store.add_activity(record)` → writes disk + `reload()`.
- [ ] Decide persistence target (recommended: separate `data/ingested/` overlay, keep seed pristine).
- [ ] Keep the retrieval index in sync after a write (auto-reindex or documented manual step).
- [ ] Fix field bugs: JA fiscal quarter via `_fy()`, rep-resolved `sales_info`, drop bogus
      `opportunity_id`.
- [ ] Add `pydantic` to `requirements.txt`.
- [ ] Add hermetic `tests/test_ingestion.py` (mock the API).
- [ ] Fill in §7 of the integration brief (surface, attribution, persistence, reindex, provider).

---

## 🧹 Housekeeping / not yet committed
- [ ] Commit the accumulated work (retrieval + dataset + ingestion/Groq wiring + docs).
      Exclude external (non-mine) changes; never commit `.env` / `senpai/.env` (Groq secret).

---

## 💡 Backlog / future ideas

### Sales-assist features (make the rep's day easier)
- [ ] **Meeting-prep brief (one-pager)** — before a customer visit, auto-assemble account health,
      open deals + ranks, last interactions, unresolved `customer_challenge`s, expansion
      opportunities, and suggested talking points + likely objections.
      *Reuses:* `account/context.py`, `account/expansion.py`, `search_notes`, `coach/cases.py`,
      `matsuda/synthesize.py`.
- [ ] **Win-probability + pipeline forecast** — calibrated close-probability per deal from
      historical win-rates by `order_rank`/category/rep (graph already computes win-rates);
      roll up to expected-revenue forecast for the manager dashboard.
      *Reuses:* `graph/query.py:reps_who_win`, order/deal data.
- [ ] **Commitment / action-item extraction** — parse daily reports for promises (見積もり送付,
      予算確認後に連絡…) → tracked follow-ups with due dates. Pairs with the ingestion work
      (a voice note becomes an activity *and* a task).
- [ ] **Competitive battlecard** — when `COMPETITION_LEXICON` fires on a deal, surface which reps
      beat that competitor, the winning playbook, and similar won cases.
      *Reuses:* `query_graph`, `retrieve_playbook`, `coach/cases.py`.
- [ ] Surface the morning briefing in the UI (a Streamlit "Today" page / Home widget), not just
      the chat tool.

### Tooling / grounding follow-ups (from the tools audit)
- [ ] Upgrade `search_knowledge` principles/approved-items scoring from keyword to hybrid
      (its playbook slice already is) so knowledge RAG matches by meaning.
- [ ] Data-model richness (optional, schema-permitting): customer `size` is categorical
      (小規模/中規模) with no revenue figure, and the product taxonomy has fixed categories.
      If finer faceting is wanted (e.g. numeric revenue bands, sub-categories), extend the seed
      generator + Schema — `find_deals` will pick up any new facet automatically via `deal_facets()`.
- [ ] Consider surfacing `find_deals` results into the chat answer as cited evidence (deal IDs)
      so advice is visibly grounded.

### Retrieval / graph polish
- [ ] Phase 2b: GraphRAG community summaries (Louvain/greedy-modularity → per-cluster LLM summary
      → retrieve over summaries) for fuzzy global questions. Documented, not built.
- [ ] Optional cross-encoder reranker (`SENPAI_USE_RERANKER`, currently off).
- [ ] Blend `similar_by_graph` into `find_similar_deals` for richer matches.
- [ ] Have `coach/context.py` pull semantically-relevant recent activities (not just newest-first).

- [ ] _(add new feature ideas here as they come up)_
