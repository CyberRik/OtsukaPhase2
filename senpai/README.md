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
   ├─ health/flags.py     ── report-reliability flags                      │ GPU-free core
   ├─ retrieval/playbook.py ── playbook + similar-deal lookup              │
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
they pass.

---

## Data — the real SPR schema

`data/gen_seed.py` deterministically generates byte-stable synthetic data **in Otsuka's
production shape**, so swapping in the real SPR export later is a drop-in. The four canonical
tables mirror [`../Schema.md`](../Schema.md) field-for-field:

| Seed file | Rows | Notes |
|---|---|---|
| `deals.json` | 60 | opportunity-level: `order_rank`, financials, `expected_order_date`/`days_until_order` |
| `sales_activities.json` | ~186 | the interaction log: `activity_date`, `daily_report`, `business_card_info`, `customer_challenge` |
| `quotes.json` | ~50 | `quote_amount`, `discount_rate`, `similar_quote_count`, `quote_expiry_date` |
| `orders.json` | ~19 | realised order lines (confirmed deals): unit prices, gross profit, supplier |

Plus **supplementary reference data** the SPR tables only reference (master data / mined,
not part of the SPR export): `reps.json` (resolved from `sales_info.employee_id`),
`customers.json`, `products.json`, `playbook.json` (mined from `daily_report`), and
`environments.json` (customer IT environment — **a known gap**, not in the four SPR tables).

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

## Tools

OpenAI function schemas (`tools/schemas.py`) + a `dispatch()` executor (`tools/impl.py`) that
returns short strings and never raises. Each chat passes its own role-scoped subset.

| Tool | Junior | Manager | Purpose |
|---|:--:|:--:|---|
| `query_spr` | ✓ | ✓ | Deals + recent activities by customer / rep / deal |
| `find_similar_deals` | ✓ | | Comparable deals for a new/thin customer |
| `retrieve_playbook` | ✓ | | Attributed senior tactics by tags/keywords |
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
.venv/bin/pip install -r requirements.txt      # gradio, openai, streamlit, pandas, pytest
```

The model is **served** by the external vLLM venv (same as the Phase-1 demo) — nothing to
install there. The dashboard and tests need none of it (pure Python).

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

## Verify (no GPU)

```bash
export SENPAI_TODAY=2026-06-16
.venv/bin/pytest tests/test_scoring.py tests/test_flags.py tests/test_manager_tools.py   # 22 tests
.venv/bin/python -m senpai.tools.impl            # one canned call per tool
python -m senpai.data.gen_seed                   # regenerate; byte-stable (re-running is a no-op)
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
