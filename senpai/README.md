# Senpai — Sales Knowledge & Deal-Health Pipeline

Senpai turns the Phase-1 fine-tuned tool-calling model (**exp3**) into a usable product for
a Japanese B2B IT sales org. One shared, deterministic engine — built **directly on
Otsuka's real SPR schema** (see [`../Schema.md`](../Schema.md)) — serves **three front
ends** and two audiences:

| Front end | Who | What | Needs GPU? |
|---|---|---|---|
| **Junior chat** (`apps/junior_chat.py`, Gradio :7860) | New reps | Pre-call briefs, playbook tactics, daily-report drafting, expert routing | yes (exp3) |
| **Manager chat** (`apps/manager_chat.py`, Gradio :7861) | Managers | "Which deals are dying?", report digests, coaching focus, draft a nudge | yes (exp3) |
| **Manager dashboard** (`apps/manager_dashboard.py`, Streamlit :8501) | Managers | Pipeline table with 🔴🟡🟢 health + report-reliability flags | **no** |

**Design thesis.** Onboarding is the relatable face; the real daily pain is pipeline
reliability — *"nobody knows if a deal is real."* So the technical core is a **hybrid
deal-health engine**: deterministic Python produces the score and the reasons (trustworthy,
GPU-free, never hallucinates a number); exp3 only *narrates* the "why" and drives the chat.
If the model server is down, narration degrades to a templated string and
scoring/flags/dashboard are unaffected.

> **Scope note.** This README covers *our pipeline*. A separate, in-progress **web-app
> experiment** (a FastAPI backend under `api/`, a Next.js frontend under `../web/`, plus the
> Sales Review Coach `coach/` and Knowledge Explorer `knowledge/`) is **owned by another team
> member**. Our pipeline does not import or depend on it. See [Isolation](#isolation-from-the-web-app-experiment) below.

---

## Architecture

```
data/store.py  ── single source of truth (committed seed JSON, real SPR schema)
   │
   ├─ health/scoring.py   ── deterministic 0–100 risk score + JP reasons   ┐
   ├─ health/flags.py     ── report-reliability flags                      │
   ├─ retrieval/playbook.py ── playbook + similar-deal lookup              │
   ├─ retrieval/semantic.py ── hybrid search: BM25 + dense (RRF-fused)     │ GPU-free core
   │    └ data/index/*      ── committed embedding vectors (build_index.py) │  (dense embeds
   ├─ graph/build.py,query.py ── knowledge graph + multi-hop queries        │   the query only)
   ├─ tools/impl.py       ── tool executors + dispatch() (never raises)    │
   ├─ tools/web.py        ── web_search (Tavily + canned fallback)         │
   ├─ tools/schemas.py    ── OpenAI schemas + JUNIOR_TOOLS / MANAGER_TOOLS  ┘
   └─ llm/
        client.py         ── OpenAI client → exp3 + tool loop (stream_turn)
        narrate.py        ── LLM narration of health, templated fallback
   │
   apps/manager_dashboard.py (Streamlit, GPU-free) ◄── scoring/flags
   apps/junior_chat.py       (Gradio, JUNIOR_TOOLS) ◄── stream_turn
   apps/manager_chat.py      (Gradio, MANAGER_TOOLS) ◄── stream_turn
```

Everything reads through `data/store.py`, so the data model lives in exactly one place. The
two chats share one tool loop (`llm/client.py:stream_turn`) and differ only by the tool set
they pass. Retrieval (semantic search + graph) and scoring are **all GPU-free**: only exp3's
narration/chat needs the model server.

---

## Data — the real SPR schema

`data/gen_seed.py` deterministically generates byte-stable synthetic data **in Otsuka's
production shape**, so swapping in the real SPR export later is a drop-in. The four canonical
tables mirror [`../Schema.md`](../Schema.md) field-for-field:

| Seed file | Rows | Notes |
|---|---|---|
| `deals.json` | 520 | opportunity-level: `order_rank`, financials, `expected_order_date`/`days_until_order` |
| `sales_activities.json` | ~2,300 | the interaction log: `activity_date`, `daily_report`, `business_card_info`, `customer_challenge` |
| `quotes.json` | ~480 | `quote_amount`, `discount_rate`, `similar_quote_count`, `quote_expiry_date` |
| `orders.json` | 280 | realised order lines (confirmed deals): unit prices, gross profit, supplier |

The seed is a **large, multi-year** pipeline (~150 customers, 520 deals across FY2023–2026:
~140 live / 280 won / 100 lost). See [`../docs/synthetic_dataset.md`](../docs/synthetic_dataset.md).

Plus **supplementary reference data** the SPR tables only reference (master data / mined,
not part of the SPR export): `reps.json` (24, resolved from `sales_info.employee_id`),
`customers.json` (150), `products.json` (29), `playbook.json` (mined from `daily_report`),
`environments.json` (customer IT environment — **a known gap**, not in the four SPR tables),
`customer_aliases.json` (auto-derived English/romaji forms for resolution), and
`rank_history.json` (a normalized order-rank change log — the Schema.md "full rank history"
gap, kept out of the field-for-field `deals` table).

**`order_rank` is the spine.** `1_Confirmed` = won · `2_A+ … 6_P` = live pipeline (lower
number = stronger) · `7_Lost`/`8_Cancelled` = dead. The open/won/dead sets and per-rank
benchmarks live in `config.py` (`OPEN_RANKS`, `RANK_BENCHMARKS`, …). Four deals (D001–D004)
are deliberately authored as dead-but-optimistic so the dashboard flags real risk on first
load.

---

## Deal-health engine

`health/scoring.py` → `score_deal(deal, activities)` returns `HealthResult(score, band,
signals)`. Seven rank-aware signals, **each reading only real SPR fields**:

| Signal | Source field(s) |
|---|---|
| staleness | latest `sales_activities.activity_date` vs rank cadence |
| rank stagnation | `rank_updated_at` vs `order_rank` benchmark |
| order date passed | `days_until_order` / `expected_order_date` |
| rank regression | `order_rank` vs `initial_order_rank` |
| missing decision-maker | `sales_activities.business_card_info` (title) |
| stall language | latest `sales_activities.daily_report` |
| low activity | gap in `sales_activities.activity_date` |

Score → 🔴 ≥55 / 🟡 25–54 / 🟢 <25; every signal carries a Japanese `reason` (no number is
ever invented by a model). `health/flags.py` → `deal_flags(...)` adds report-reliability
checks: `close_date_passed`, `stale_active`, `missing_fields`, `optimism_mismatch` (strong
`order_rank` but red health), `unsupported_rank`.

---

## Retrieval — semantic search + knowledge graph

Beyond keyword/tag lookup, Senpai retrieves by **meaning** and by **relationships**. Both are
GPU-free and degrade gracefully. Full details: [`../docs/retrieval.md`](../docs/retrieval.md).

- **Hybrid semantic search** (`retrieval/semantic.py`). **BM25** (Japanese, Janome-tokenized,
  content-words only) ⊕ **dense embeddings** (fastembed/ONNX, multilingual-MiniLM), fused with
  **Reciprocal Rank Fusion** (dense-weighted). Corpus vectors are precomputed and **committed**
  (`data/index/`, built by `retrieval/build_index.py`), so only the live query is embedded.
  Degrades `dense+BM25 → BM25 → keyword` when libs/vectors are absent. `retrieve_playbook` uses
  this internally; the `search_notes` tool exposes it over the ~2,300 daily reports.
- **Knowledge graph** (`graph/build.py`, `graph/query.py`). A `networkx`
  customer→deal→activity→rep→product graph, built from the store at runtime, answers multi-hop
  questions via the `query_graph` tool: `reps_who_win` (e.g. *"who wins サーバー deals in 製造業
  after a site survey"*), `account` (an account's whole network), `connections`, `similar`.

Quality is covered by `scripts/stress_retrieval.py` (paraphrase recall, fusion sanity,
determinism, fuzz robustness, latency) on top of the unit tests.

---

## Tools

OpenAI function schemas (`tools/schemas.py`) + a `dispatch()` executor (`tools/impl.py`) that
returns short strings and never raises. Each chat passes its own role-scoped subset.

| Tool | Junior | Manager | Purpose |
|---|:--:|:--:|---|
| `query_spr` | ✓ | ✓ | Deals + recent activities by customer / rep / deal |
| `find_similar_deals` | ✓ | | Comparable deals for a new/thin customer |
| `retrieve_playbook` | ✓ | | Attributed senior tactics (hybrid semantic ranked) |
| `search_notes` | ✓ | ✓ | Semantic search over daily reports (finds paraphrases) |
| `query_graph` | | ✓ | Multi-hop graph: who-wins-what, account network, connections |
| `lookup_customer_environment` | ✓ | | Customer PC/OS/network record |
| `get_product_info` | ✓ | | Specs/price/manual excerpt + category |
| `score_deal_health` | ✓ | ✓ | A deal's band + risk + reasons |
| `draft_daily_report` | ✓ | | SPR-ready 日報 draft |
| `route_to_expert` | ✓ | | Match a senior/expert + intro message |
| `get_seasonal_context` | ✓ | | Japanese fiscal-year budget timing |
| `list_at_risk_deals` | | ✓ | Team-wide at-risk deals, worst-first |
| `team_pipeline_overview` | | ✓ | Counts, ¥, rank spread, health split, flags |
| `team_report_digest` | | ✓ | All reps' flagged deals, grouped |
| `rep_coaching_focus` | | ✓ | Per-rep rollup → where to coach |
| `draft_message` | | ✓ | Editable rep-nudge / client follow-up (never sent) |
| `web_search` | ✓ | ✓ | External research; also enables normal chatbot use |

---

## Setup

From the repo root (`OtsukaPhase2/`):

```bash
.venv/bin/pip install -r requirements.txt
# core: gradio, openai, streamlit, pandas, pytest
# retrieval: fastembed (ONNX/CPU), rank-bm25, janome, networkx — all GPU-free
```

The model is **served** by the external vLLM venv (same as the Phase-1 demo) — nothing to
install there. The dashboard, retrieval and tests need none of it (pure Python / CPU).

The semantic index is **committed** under `data/index/`. Only rebuild it after changing the
seed or the tokenizer/embedding model (downloads the embed model once, then runs offline):

```bash
python -m senpai.retrieval.build_index          # writes data/index/* (byte-stable)
```

## Run

```bash
export SENPAI_TODAY=2026-06-16     # pin scoring's "today" to the seed anchor (reproducible)

# Manager dashboard — no GPU, no model server
.venv/bin/streamlit run senpai/apps/manager_dashboard.py     # http://localhost:8501

# Chats — need exp3 served
./scripts/serve_model.sh                                     # exp3 on :8765 (needs GPU)
.venv/bin/python senpai/apps/junior_chat.py                  # junior  → http://localhost:7860
.venv/bin/python senpai/apps/manager_chat.py                 # manager → http://localhost:7861
```

Sanity-check the server before a chat demo:
`curl -s localhost:8765/v1/models | python3 -m json.tool` → should list `exp3`.

`web_search` returns canned Japanese results offline; for live results put
`TAVILY_API_KEY=...` in a repo-root `.env`.

## Configuration (env vars)

| Var | Default | Used by | Meaning |
|---|---|---|---|
| `BASE_URL` | `http://127.0.0.1:8765/v1` | `llm/client.py` | vLLM OpenAI endpoint |
| `MODEL` | `exp3` | `llm/client.py` | Served model name |
| `SENPAI_TODAY` | unset → real date | `config.today()` | Pin scoring's "today" (e.g. `2026-06-16`) |
| `UI_HOST` / `UI_PORT` | `127.0.0.1` / `7860`,`7861` | chats | Bind address / port |
| `TAVILY_API_KEY` | — | `tools/web.py` | Enables real web search |
| `SENPAI_USE_EMBEDDINGS` | `1` | `retrieval/semantic.py` | Dense layer on; `0` = BM25-only |
| `SENPAI_USE_RERANKER` | `0` | `retrieval/semantic.py` | Optional cross-encoder rerank |
| `SENPAI_EMBED_MODEL` | MiniLM-multilingual | `build_index.py` | fastembed model id |
| `SENPAI_DENSE_WEIGHT` / `SENPAI_BM25_WEIGHT` / `SENPAI_RRF_K` | `3` / `1` / `60` | `semantic.py` | Fusion tuning |

## Verify (no GPU)

```bash
export SENPAI_TODAY=2026-06-16
.venv/bin/pytest -q                              # full suite (hermetic, BM25-only retrieval)
.venv/bin/python -m senpai.tools.impl            # one canned call per tool (incl. search_notes / query_graph)
python -m senpai.data.gen_seed                   # regenerate seed; byte-stable (re-run is a no-op)

# Retrieval-specific:
SENPAI_TEST_DENSE=1 .venv/bin/pytest tests/test_semantic.py tests/test_graph.py   # incl. dense path
.venv/bin/python scripts/stress_retrieval.py     # stress harness: paraphrase recall, fuzz, latency
```

---

## Isolation from the web-app experiment

A separate, in-progress **web application** (owned by another team member) lives alongside
this pipeline: a FastAPI backend (`api/server.py`), a Next.js frontend (`../web/`), and the
Sales Review Coach (`coach/`) + Knowledge Explorer (`knowledge/`) engines, surfaced through
extra Streamlit pages (`apps/review_coach.py`, `apps/knowledge_review.py`, `apps/pages/`).

Our pipeline is **decoupled** from it:
- Importing our modules loads **zero** `coach`/`knowledge` code (the one bridge,
  `review_sales_note`, imports the coach lazily and is **not** in our chat tool set).
- The web app reuses our deal-health engine. To keep it running unchanged against the new
  schema, each deal row carries a few **legacy alias fields** (`stage`, `amount`,
  `expected_close_date`, …) and `store` keeps `notes_for_deal` / `report_for_deal` compat
  shims. These are **temporary scaffolding** for that experiment — not part of the SPR schema
  — and can be removed once it migrates.

If you only care about our pipeline, ignore `api/`, `coach/`, `knowledge/`, the extra
`apps/` pages, and `../web/`.

---

## PM demo run sheet

1. **Lead with the human story** — junior chat: 「明日アクメ商事に訪問。準備をお願い」 →
   deal + playbook + environment + health in one brief; 「お客様が決定を先延ばしにします。
   先輩ならどうしますか？」 → an attributed senior tactic (or an expert hand-off).
2. **Switch to business impact** — manager chat or dashboard: 「今週リスクが高い案件を担当別に
   まとめて」 / drill into **D001** for the signal-by-signal breakdown; the report-reliability
   panel is "the dead deals we flag in week one."
3. **Show it never breaks** — stop the model server, reload the dashboard: narration falls back
   to a templated reason; scoring and flags are unchanged.

Same engine, two audiences: the junior's pre-call brief and the manager's risk view are the
*same* deterministic health read, phrased for each.
