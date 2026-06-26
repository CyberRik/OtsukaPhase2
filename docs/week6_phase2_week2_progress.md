# Senpai — Progress Report
### Internship Week 6 · Phase 2, Week 2 · June 2026
**Team:** AI Department (intern team) · **Audience:** Manager / mentors / Givery team
**Project:** Senpai — Sales Knowledge & Onboarding Copilot for Otsuka Shokai

---

## 0. Executive Summary

This week we transformed Senpai from a working prototype into a credible, production-shaped
system. The core engine remained deterministic and grounded — we never moved that principle —
but we expanded it across five major directions simultaneously:

1. **Performance.** A memoized index layer cut coaching API latency from ~7s to ~140ms (~54×
   faster) and the full test suite from 36s to 1.4s.
2. **Expanded intelligence surfaces.** Account Intelligence (8-dimension customer health),
   Morning Briefing (urgency-ranked action list), and a full Account Expansion engine (cross-sell /
   upsell / growth opportunities).
3. **Deeper coaching.** Rep coaching profiles, fiscal-year progress tracking, coaching threads,
   a coaching explainability layer, and a growth/motivation portal — all deterministic.
4. **Document generation.** Four new tools: `generate_proposal` (4-slide PPTX from SPR data),
   `generate_ringisho` (Japanese 稟議書 DOCX), `generate_pptx` (free-prompt general PPTX),
   `generate_docx` (free-prompt general DOCX) — all grounded, two-step confirm before file creation.
5. **Retrieval evolution.** Hybrid BM25 + dense vector search with Reciprocal Rank Fusion,
   a runtime knowledge graph (744 nodes) with multi-hop queries, and a `search_notes` tool
   surfaced to the model — making the system meaning-aware without GPU at runtime.
6. **Workspace shell.** A unified conversational surface replacing the old split
   Assistant + Coach pages — slash commands, immutable artifacts, streaming senior reads,
   file attachment, and multi-sheet XLSX export.
7. **Ingestion via Paperclip.** A multimodal ingestion pipeline (audio/image/text) that writes
   structured `sales_activities` records through an editable draft UI — closing the capture loop
   so the knowledge base can grow from real field activity.

The total test suite grew to **116 tests (1 skipped)** across 17 test files. All engine APIs
remain GPU-free.

---

## 1. Architecture principles that held this week

Everything new was built against the same design spine established in Week 1:

| Principle | How it was upheld this week |
|---|---|
| **Deterministic first** | Every new subsystem (account health, expansion, morning briefing, coaching profile, progress, explainability, growth) computes its output in pure Python. The LLM only narrates the already-computed package. |
| **LLM as presentation layer** | `generate_proposal` / `generate_ringisho` inject numbers from the deterministic `DocumentContext`; the LLM writes only the value-proposition line and the 稟議書 prose. Numbers never come from the model. |
| **Grounded or silent** | Every new API endpoint includes a strict grounding contract ("never invent", "quote numbers exactly", "refer to signals by `[id]`"). On LLM failure, the deterministic summary is served unchanged. |
| **Single source of truth** | All new engines read through `store.py` — nothing bypasses the central data layer. |
| **Overlay persistence** | Ingested activities append to a gitignored overlay layer; the committed seed is never mutated. |
| **Knowledge / Experience / Motivation loop** | Week 1 established these as the design spine. This week's growth portal (§7), coaching progress (§6.2), and morning briefing (§5) close the loop explicitly. |

---

## 2. Performance — Store Indexing

**Problem.** Hot paths in the coaching engine (e.g. `coach.cases`, which finds similar deals
across thousands of activity comparisons) called relational accessors like
`activities_for_deal()`, `orders_for_customer()`, `quotes_for_customer()` in inner loops.
Each call linearly scanned the full table. At scale this produced O(rows × calls) work.

**Fix.** `senpai/data/store.py` — a new `_index()` function, memoized with `@lru_cache(maxsize=1)`,
builds **per-key dictionaries once** at first access and is dropped automatically on `reload()`.
Every relational accessor is now an O(1) dictionary hit.

```python
@lru_cache(maxsize=1)
def _index() -> dict:
    acts_by_deal: dict[str, list[dict]] = {}
    for a in all_activities():
        acts_by_deal.setdefault(a.get("deal_id"), []).append(a)
    # … orders_by_cust, quotes_by_cust, deals_by_rep, deals_by_cust …
    return { … }

def activities_for_deal(deal_id: str) -> list[dict]:
    return _index()["acts_by_deal"].get(deal_id, [])
```

The index is **result-sorted** (activities: newest-first by `activity_date`; orders:
newest-first by `ordered_at`) so callers never need to sort their own slices.

**Measured impact:**

| Endpoint | Before | After | Speedup |
|---|---|---|---|
| `/api/coach/review` (coaching) | 7.7 s | 181 ms | **~43×** |
| `/api/coach/rep-profiles` | 7.4 s | 137 ms | **~54×** |
| Full `pytest` suite | 36.4 s | 1.4 s | **~26×** |

---

## 3. Retrieval Evolution — Hybrid Semantic Search + Knowledge Graph

### 3.1 Hybrid semantic search (`senpai/retrieval/`)

The original retrieval was keyword/tag matching. This week we built a full two-signal hybrid
stack — GPU-free at runtime.

**Build step (`retrieval/build_index.py`):**
- Embeds each corpus (daily reports, playbook entries) with **fastembed** (ONNX/CPU,
  `paraphrase-multilingual-MiniLM`, 384-d) and **commits** the artifacts to `senpai/data/index/`.
- Runtime never needs a GPU or model download for the corpus side — only the live query
  is embedded (one short CPU call).
- Committed artifacts: `{corpus}.npy` (L2-normalized float32 matrix), `{corpus}.meta.json`
  (per-row metadata + raw text), `{corpus}.tokens.json` (precomputed BM25 tokens),
  `manifest.json` (model, dim, per-corpus count + content hash).

**Runtime search (`retrieval/semantic.py`):**
- **BM25 (lexical)** over Janome-tokenized, POS-filtered text (nouns/verbs/adjectives/
  adverbs only — particles and light verbs removed so function words don't pollute ranking).
- **Dense cosine** against committed vectors.
- **Reciprocal Rank Fusion** (`score = Σ 1/(k+rank)`) with `DENSE_WEIGHT=3` vs `BM25_WEIGHT=1`
  (embedding is the stronger paraphrase signal, BM25 still helps exact-term queries).
- **Text-space deduplication** before fusion: duplicate daily reports don't flood either
  signal's candidate pool.
- **Graceful degrade:** `dense + BM25 → BM25 only → keyword substring` — the richest
  available layer wins. `semantic.mode()` reports which layer is active.

**Surfaced to the model:**
- `search_notes` tool: semantic search over daily reports (日報), clamped to ≤6 results to
  cap synthesis input size.
- `retrieve_playbook` internally upgraded to this layer (same signature, backward-compatible).

**Stress tested** via `scripts/stress_retrieval.py`. Key lessons encoded in the design:
the word-boundary rule for ASCII keys (`\b` for `new` so it doesn't match `news`), and the
content-word tokenizer that stops BM25 from over-matching function words.

### 3.2 Knowledge graph (`senpai/graph/`)

A `networkx.MultiDiGraph` built from the store at runtime (cached; never drifts from the
seed data).

**Nodes:** `rep` · `customer` · `deal` · `product` · `industry:*` · `category:*` · `acttype:*`

**Edges:** `OWNS` · `FOR` · `CONCERNS` · `IN_CATEGORY` · `IN_INDUSTRY` · `HAD`

Deal nodes are **denormalized** with category/industry/outcome/rep/products/acttypes so
filter traversals are a fast scan rather than expensive graph walks.

**Current graph size: 744 nodes.**

**Parameterized query functions (`graph/query.py`):**
- `reps_who_win(category, industry, after_activity_type)` — "which reps win サーバー deals in
  製造業 after a site survey?" (relational question the flat retrieval layer can't answer).
- `account_graph(customer_id)` — full neighborhood of an account: deals, reps, products.
- `connections(a, b)` — shortest relational path between two entities.
- `similar_by_graph(deal_id)` — deals sharing rep/product/industry/category.

**Surfaced to the model:** `query_graph` tool (intent = `reps_who_win | account | connections | similar`).

---

## 4. Account Intelligence (`senpai/account/`)

Deal health answers "is **this opportunity** on track?" Account Intelligence answers "is
**this whole customer relationship** healthy and growing?" — a distinct, higher-level read
that a senior account manager would give.

### 4.1 Account health engine (`account/health.py`)

`account_health(customer_id)` → 0–100 score, band, 8 dimensions, human-readable reasons.

**Higher-is-better** (inverse of deal risk, so the two scores are never confused).

| Dimension | Weight | Signal |
|---|---|---|
| `activity_trend` | 15 | recent-90d vs prior-90d activity ratio |
| `inactivity` | 10 | days since last activity (decays 14→90d) |
| `pipeline_progression` | 15 | open deals advanced vs slipped by `order_rank` |
| `win_rate` | 15 | won / (won+lost) closed deals |
| `quote_engagement` | 10 | recent quotes + quote→order conversion |
| `order_recency` | 15 | recency of last order + repeat-order count |
| `dm_access` | 10 | share of open deals with a decision-maker identified |
| `growth` | 10 | recent-180d vs prior-180d order revenue |

**Bands:** ≥70 green (healthy/strategic), 45–69 yellow (watch), <45 red (at risk).
`AccountHealth.top_reasons(n)` returns the weakest dimensions for the commentary contract.

### 4.2 Relationship trajectory (`account/trajectory.py`)

`relationship_trajectory()` runs deterministic pattern matchers over account aggregates,
each emitting a `Pattern(id, label, evidence, polarity)` with a concrete evidence string.

- **Positive patterns:** `repeat_purchasing`, `activity_increasing`, `expansion_potential`
- **Risk patterns:** `activity_declining`, `spend_declining`, `multiple_stalled` (≥2 red
  open deals), `engaged_no_progress` (high contact, zero advancement/revenue),
  `loyal_dormant` (past wins but ≥60d silent)

### 4.3 Account expansion engine (`account/expansion.py`)

Three families of opportunity, all grounded in store records. The only authored content is
a static category adjacency map and a list of environment trigger phrases.

1. **Cross-sell** — gap categories *complementary* to what the account already owns
   (`_COMPLEMENTS` adjacency over the 7 catalog majors: OA機器, PC周辺機器, サーバー, etc.).
2. **Upsell** — environment upgrade triggers matched against the customer's IT environment
   record (`ADSL|更改検討|老朽` → ネットワーク機器; `Windows 10|EOL` → PC周辺機器;
   `無線LAN|Wi-Fi` → ネットワーク機器).
3. **Growth** — engaged account (≥2 open deals) with thin category coverage (≤2) →
   strategic-account flag.

Each `Opportunity(kind, target, rationale, evidence, confidence)` carries its own grounding.

### 4.4 Account summary and commentary (`account/summary.py`, `account/context.py`)

`build_account_summary(customer_id)` rolls up health, trajectory, and expansion into one
`AccountSummary` — industry/size, pipeline ¥, historical revenue, last activity, recent
quotes/orders, IT environment, a `recommended_focus` line (deterministic, no LLM required).

The commentary endpoint streams a senior account-manager's read under a four-heading
contract (Account Reality / Single Deal vs Whole Account / The Real Risk / Recommended Focus)
with strict grounding rules: ground every statement in the context, quote numbers exactly,
refer to signals by `[id]`, never invent.

### 4.5 API and frontend

| Endpoint | Output |
|---|---|
| `GET /api/account/{id}` | `AccountSummary.to_dict()` — deterministic |
| `POST /api/account/{id}/commentary` | SSE — streamed senior read |
| `GET /api/customers/resolve?q=…` | Deterministic name→id resolution |
| `POST /api/customers/smart-resolve` | Deterministic + fuzzy + LLM-ranked resolution |

**Frontend (`web/components/account/`):**
- `accounts-index.tsx` — discoverability surface: rolls open-deal pipeline up by customer
  (worst band, open count, pipeline ¥), sorted by pipeline value. No extra backend call —
  reuses the existing dashboard payload.
- `account-view.tsx` — the full Account Intelligence page: 8 health dimensions, risk/expansion
  signals, recent quotes/orders, IT environment, open-deal drawer, streamed senior read.

Both views are role-aware (`junior | manager`) and mount identical components.

---

## 5. Morning Briefing (`senpai/briefing.py`)

A prioritized next-best-action worklist that a rep reads at the start of their day.

**How it works:**
1. Sweeps all of a rep's open deals.
2. Scores each with the deterministic health engine.
3. Ranks by `urgency × value` where urgency is the health risk score and value is the
   deal's expected order amount.
4. Attaches **one concrete next action per deal**, derived from the dominant risk signal:

   | Signal | Action |
   |---|---|
   | `order_date_past` | 受注時期を再確認し、完了予定日を更新する |
   | `missing_dm` | 決裁者を特定する (役職者へのアプローチを設定) |
   | `staleness / low_activity` | 今日フォローの連絡を入れる (N日間接触なし) |
   | `stall_language` | 停滞の要因をヒアリングし、次の一手を決める |
   | `rank_regression` | ランク下降の原因を確認し、挽回策を立てる |

5. Adds a **predictive cadence nudge**: deals that are *about to* breach their rank's
   contact cadence — but haven't gone stale yet — surface before they turn yellow.

**Why it matters:** the briefing is as auditable as the scoring engine because every action
derives from the same `score_deal` signals and `RANK_BENCHMARKS` cadence constants. No model
invents the action. The briefing degrades to the deterministic summary if the model is offline.

**Tool wired:** `morning_briefing(rep_id, limit)` added to both junior and manager tool sets.
Tests: `tests/test_briefing.py`.

---

## 6. Expanded Coaching Platform

### 6.1 Enriched synthetic data (rep skill model)

The synthetic data generator (`data/gen_seed.py`) was upgraded with a **deterministic per-rep
skill model** (`REP_SKILL`). Each rep has characteristic weakness themes (juniors more,
experts fewer) and some juniors are flagged **improving** (their notes get more complete over
fiscal years).

- Only 3 activity fields change via a local RNG keyed on each activity (`daily_report`,
  `business_card_info`, `customer_challenge`) → SPR tables (deals/quotes/orders/amounts/dates)
  stay **byte-identical**.
- Reports now span a realistic quality spread (≈26% thorough → tapering to thin) instead of
  the old uniform 2–5 lens fill.
- **Coaching threads** (`data/seed/coaching_threads.json`): deterministic manager↔rep chat
  raised on flagged deals — `issue_key`, `status ∈ {open, acknowledged, resolved}`, dated
  `messages`. Resolved threads correlate with the improving-rep flag, giving `rep_progress`
  its acted-on signal.

### 6.2 Rep coaching profile (`senpai/coach/profile.py`)

`rep_coaching_profile(employee_id)` aggregates deterministic coaching issues across a rep's
whole book into a 1:1 brief:

- Weaknesses ranked by **severity then frequency** (missing decision-maker outranks report hygiene)
- Each weakness carries: count + **real example deals** + a **validated principle** (`knowledge/`) +
  a **real past case** (`coach.cases`) + one **concrete action**
- **Strengths**, a headline **development focus** (with explainability card), **1:1 talking points**
- **Coaching-thread status** (how many resolved, open, acknowledged)

`team_coaching_profiles()` rolls this up across the whole team for the manager.

API: `GET /api/coach/rep-profile/{id}`, `GET /api/coach/rep-profiles`.

### 6.3 Rep progress (`senpai/coach/progress.py`)

`rep_progress(employee_id, windows=4)` replays the engine **as of each of the last fiscal years**
(scoring each deal at its last in-window activity to avoid false staleness signals) and produces:
- Per-issue **trend** over time (improving/flat/worsening)
- Overall headline: 改善傾向 / 横ばい / 悪化傾向
- **Coaching acted-on rate** from threads (was past coaching resolved?)

This closes the feedback loop: the coaching engine *rediscovers* the weaknesses seeded into
the rep skill model — a seeded decision-maker-weak rep surfaces `missing_decision_maker`, and
an improving discovery-weak rep visibly trends down.

API: `GET /api/coach/rep-progress/{id}`.

### 6.4 Coaching explainability (`senpai/coach/explainability.py`)

For every coaching recommendation (lens, signal, flag, issue), `build_explanation()` assembles
a grounded explanation in four parts:

1. **Trigger Conditions** — which rule fired and what data matched
2. **Supporting Evidence** — the actual field values behind the trigger
3. **Similar Historical Cases** — real closed deals with the same pattern
4. **Outcome Statistics** — win/loss rates computed from `store.all_deals()` only
   (returned as `None` when fewer than `MIN_SAMPLE=5` closed deals match — never interpolated)

Frontend: `web/components/coach/` explainability cards.
Tests: `tests/test_explainability.py`.

---

## 7. Growth / Motivation Portal (`senpai/growth.py`)

Closes the **Motivation** pillar of the Knowledge / Experience / Motivation loop.

A read-only analytics layer that turns a rep's real activity history into visible progress
markers — purpose is encouragement, not grading.

**Five skills, each derived from a transparent ratio over real deals:**

| Skill | Signal |
|---|---|
| `relationship_building` | Repeat-visit activity rate |
| `decision_maker_discovery` | Share of deals with business_card_info filled |
| `customer_discovery` | Share of activities with customer_challenge filled |
| `closing_discipline` | Order-rank advancement rate |
| `proposal_pricing` | Quote-to-order conversion rate |

Each daily report is treated as one completed coaching review (rep reflecting on a call) —
the closest real proxy to "reviews completed" without persisting app usage.

Frontend routes: `web/app/junior/` and `web/app/manager/` growth pages.

---

## 8. Document Generation Tools (`senpai/documents/`)

Four new tools add a **document output layer** to the assistant — one of the highest-value
actions a rep takes when a deal is near closing.

### 8.1 `generate_proposal` — 4-slide PPTX sales proposal

Grounded entirely in the deal's SPR data via `DocumentContext` (built by `documents/context.py`):

| Slide | Content | Source |
|---|---|---|
| 1 — Title | Customer name + value proposition | LLM narration (one line only) |
| 2 — 課題 | Up to 5 pain points | `sales_activities.customer_challenge` + `daily_report` |
| 3 — ソリューション | Matched catalog products with codes + prices | `products.json` |
| 4 — 投資対効果 & 次のステップ | Deal financials (HW/SW/services splits) + comparable deals | SPR `total_order_amount`, `quotes` |

**Design principle:** all ¥ numbers come from the deterministic `DocumentContext`. The LLM
writes only the value-proposition subtitle. A footnote on each slide states its data source.

### 8.2 `generate_ringisho` — 稟議書 (DOCX)

A formal Japanese internal-approval document written from the **customer's IT-manager persona
pitching their own CEO**. Structure:

1. 背景・課題 — grounded in SPR pain points
2. 提案内容 — grounded in catalog products
3. 投資額と効果 — injected from `DocumentContext.financials` (never invented)
4. 結論・承認依頼
5. 承認欄

LLM writes the prose sections; the financial table is a deterministic injection.

### 8.3 `generate_pptx` / `generate_docx` — general-purpose document tools

Free-prompt LLM-authored documents, optionally grounded by internal records (`/api/account`)
or web search. **Two-step confirm** before any file is created (the model surfaces a slide/
section outline; the user confirms before the file is written). Both degrade cleanly when
the model is offline.

### 8.4 Download flow

All four tools save to `config.GENERATED_DIR` and return a download path. The web UI exposes
a download button. Smoke-tested with `python -m senpai.documents.proposal D001` and
`python -m senpai.documents.ringisho D001`.

Tests: `tests/test_documents.py` — the deterministic proposal/ringisho path is fully covered
(no GPU); general PPTX/DOCX tests assert clean degradation when `SENPAI_USE_LLM` is off.

---

## 9. Workspace Shell (`web/components/workspace/`)

The Workspace replaces the old split `Assistant` + `Review Coach` pages with one conversational
surface where deterministic skills, grounded artifacts, and ordinary chat coexist.

### 9.1 Three skills (slash commands)

| Command | Backend | Produces |
|---|---|---|
| `/review <note or deal id>` | `POST /api/coach/review` + SSE narrate | **review** artifact — 6 teaching sections + streamed senior read |
| `/account <name or id>` | `GET /api/account/{id}` + SSE commentary | **account_brief** artifact — health, risk signals, expansion, focus + streamed read |
| `/research <question>` | `POST /api/chat` (research role) → SSE | **research** artifact — source ledger + grounded answer + web citations |
| *(bare turn)* | `POST /api/chat` (junior/manager tool-loop) | normal chat reply with tool ledger |

The *user*, never an intent-classifier, decides which skill runs — the trust boundary stays legible.
Unknown commands are rejected, not silently reinterpreted.

### 9.2 Artifact model

An **Artifact** is the typed, immutable, grounded output of a skill:

- **Immutability:** a skill never edits an artifact in place. Re-running appends a new artifact
  that `supersedes` the previous one.
- **Deterministic provenance:** `evidence` carries source IDs only (deal/SPR/principle/
  playbook/web IDs). The LLM is never the source of an evidence entry.
- Evidence IDs are parsed with a strict regex (`/^(PB\d+|P\d+|I\d+|D\d+)$/`); a stray human
  name can never become evidence.

Three assemblers — `assembleReviewArtifact`, `assembleAccountArtifact`, `assembleResearchArtifact`
— map existing API payloads into artifacts and add no facts.

### 9.3 Unified rendering

The old three duplicated card renderers were collapsed into a single `ArtifactBody` driven
by a `KIND_META` table (per-kind header, alert, commentary placement).
Sub-components: `Markdown`, `SectionBlock`, `CommentaryBlock`, `EvidenceDrawer`.

### 9.4 File attachment to context (Part A)

The chat input now supports **file attachment**: a user can clip a file and its text content
is injected into the next turn's context — grounding the conversation in an uploaded document
without a separate ingestion round-trip. Captured via a "Capture card" that is editable before
submission.

### 9.5 Multi-sheet XLSX export

Every ready artifact carries an **Export** button that downloads a real `.xlsx` via
`write-excel-file/browser` (dynamically imported, no SSR).

**Trust model:** export is a **serializer, not a generator** — only reformats the already-grounded
artifact, adds no facts, LLM touches nothing. Two sheets:
- **Brief** — heading + meta + each section + senior read commentary
- **Sources** — evidence table (deal/SPR/principle/playbook/web IDs + URLs)

Provenance travels into the file so the workbook stays auditable after it leaves Senpai.

---

## 10. Ingestion via Paperclip (`senpai/ingestion/`)

Closes the capture loop: field activity → structured SPR record → live in the engine.

### 10.1 Multimodal ingestion pipeline (`ingestion/pipeline.py`, `ingestion/multimodal.py`)

`MultimodalIngestor` processes three input types:
- **Audio** (voice memos) via Whisper → transcript
- **Images** (business cards, whiteboards) via Vision/OCR → extracted text
- **Text** — direct

All modalities feed a structured extraction step (LLM → `ActivityExtraction` Pydantic schema)
that maps raw input to the exact `sales_activities` fields:
`activity_type`, `business_card_info`, `product_major_category`, `customer_challenge`, `daily_report`.

### 10.2 Editable draft UI

Extracted data becomes a **Capture card** in the Workspace — all five fields are editable
before the rep confirms. The human review gate means hallucinations can be corrected before
they enter the knowledge base.

### 10.3 Persistence (`ingestion/persist.py`)

`build_activity_record()` produces a record in the **exact seed shape** — fiscal year/quarter
from the Japanese fiscal calendar (`config.fiscal_year_quarter`), department/division from the
rep record, `days_since_last_order` / `total_order_count` derived from the customer's orders.

`store.append_activity()` writes to the gitignored overlay (`config.INGESTED_DIR`) and drops
the `_index` / `_load` caches — the next request reads the new activity like any committed row.
The committed seed is never touched.

Tests: `tests/test_ingestion_persist.py`.

---

## 11. Additional Tools Added

The tool set grew from 18 to **38 functions** in `senpai/tools/impl.py`.

New tools added this week:

| Tool | What it does |
|---|---|
| `find_deals` | Schema-driven faceted deal search — `product_category, industry, size, outcome, order_rank, profile_tags, min_amount, max_amount, product_code, limit` — all SPR fields, no invented filters |
| `search_notes` | Semantic search over daily reports (日報) — meaning-aware, BM25+dense |
| `query_graph` | Multi-hop knowledge graph queries (`reps_who_win`, `account`, `connections`, `similar`) |
| `search_knowledge` | Semantic search over validated knowledge principles + playbook |
| `search_products` | Faceted product catalog search (`category, max_price, product_code`) |
| `create_quote` | Draft a quote from catalog items with discount, grounded in real prices |
| `get_calendar` | Calendar lookup for scheduling context |
| `morning_briefing` | Urgency-ranked daily action list (§5) |
| `generate_proposal` | 4-slide PPTX from SPR deal data (§8.1) |
| `generate_ringisho` | 稟議書 DOCX (§8.2) |
| `generate_pptx` | Free-prompt general PPTX (§8.3) |
| `generate_docx` | Free-prompt general DOCX (§8.3) |
| `schedule_meeting` | Two-step Google Calendar booking (draft → confirm → real event) |

`schedule_meeting` received a **two-step confirm** upgrade: `confirm=False` returns a draft
for human review; `confirm=True` lazily imports `gcal` and books, with `（シミュレーション）`
fallback if the Calendar call fails.

---

## 12. Latency Investigation and Router/Model Evals

Full details in `docs/phase25_session_log.md`. Summary of decisions:

### 12.1 Latency investigation (prompt + routing, no model change)

Baseline: ~395s end-to-end on a multi-tool research turn.
- **Tool-selection round (~23s):** capping `<think>` buys ~nothing — left intact.
- **Final synthesis (~230s):** dominates. Lever is input/output *size*, not think budget.

Three changes landed:
1. Parallel tool calls: system prompts now instruct the model to emit independent lookups in
   one turn (fewer sequential selection rounds).
2. Router rule: all-retrieval multi-tool turns → FAST mode (no reasoning needed for pure
   data retrieval).
3. `search_notes` clamp: `limit` clamped to ≤6 (caps dominant synthesis input).

**Result: ~395s → ~256s.**

### 12.2 Atlas intent-router evaluation (offline, NOT shipped)

63 hand-labeled bilingual queries, `LogisticRegression` on MiniLM embeddings, 5-fold CV.

- Destination head (research/tool/chat): ~0.82 — usable but not a clear win over rules.
- Mode head (fast/think): ~tie with `DeterministicReasoningRouter` — rules already as good.
- Tool-hint head (which tool): ~0.49 — not separable in MiniLM space.

**Decision: do not build Atlas.** Rules win on simplicity and on the mode head.

### 12.3 Model decomposition (in progress)

Question: can the final synthesis step use a smaller model (Qwen3-8B) for a latency win
while the 27B keeps doing tool selection?

Round 1 (bf16-8B vs Q4_K_M-27B, 4 FAST queries):

| Arm | Avg latency | Grounding fidelity |
|---|---|---|
| 27B Q4_K_M | 64.9s | 0.957 |
| 8B bf16 | 58.5s | 0.961 |

Speedup only ~1.11× because both move similar bytes/token (bf16-8B ~16GB ≈ Q4-27B ~14GB).
**Key finding: an 8B achieves parity grounding quality.** Round 2 (Q4_K_M 8B, ~5GB → ~3×
fewer bytes/token) is pending; expected ~3× synthesis speedup.

---

## 13. SSE Event Protocol and Resolution Improvements

### 13.1 Customer resolution — word-boundary rule

Fixed a live `news → new` false match. ASCII/romaji alias keys now require regex word
boundaries (`\b`); Japanese keys keep substring matching (no word boundaries in JA text).

```python
def _key_in_text(key, low_text):
    if key.isascii():
        return re.search(r"\b" + re.escape(key) + r"\b", low_text) is not None
    return key in low_text
```

Added `C##` customer-id recognition alongside `D###` deal-ids in free-text extraction.

### 13.2 Tool-calling fix (no-think suppression bug)

**Symptom:** "setup a meeting" narrated a fake `[ツール呼び出し]` instead of calling the tool.
**Root cause:** `TOOLLOOP_NO_THINK` empty-`<think>` prefill in the **selection** round suppressed
tool emission.
**Fix:** selection rounds now use `_prep(convo, False)` (keep think) + a prompt directive
"call tools directly, don't narrate". A/B test confirmed: `NOTHINK_ON` → 0 tool calls,
`NOTHINK_OFF` → `schedule_meeting` called correctly.

### 13.3 Reasoning leak fix

`_strip_reasoning` generalized to handle `<think>`, `<thinking>`, `<analysis>`, `<reasoning>`
tag variants. Research summarizers routed through `_strip_reasoning`.

### 13.4 Health engine double-count bug fix (`9194756`)

`staleness` and `low_activity` signals were **both firing on the same silence** condition,
double-penalizing deals that had no recent activity. Fixed in `senpai/health/scoring.py` +
`flags.py` so the two signals are mutually exclusive (staleness subsumes low_activity).
`tests/test_scoring.py` gained 15 new assertions covering this exact edge case.

---

## 14. Quality Assurance Infrastructure

Beyond the pytest suite, this week added three categories of test/audit tooling:

### 14.1 Stress pipeline (`scripts/stress_pipeline.py`)

A hermetic robustness harness (no GPU, no network) that probes 7 aspects of the
deterministic core in one run:

1. **Tool dispatch** — every tool survives empty / garbage / hostile args and never raises
   (the chat loop must never crash); valid calls produce non-empty output.
2. **Scoring engine** — edge cases (empty fields, missing dates, junk values, every
   `order_rank` value); score always in 0–100 with a valid band.
3. **Flags engine** — same edge cases; never crashes.
4. **Morning briefing** — every rep + team + unknown rep; sorted, grounded, deterministic.
5. **`find_deals`** — facet filters honoured, outcome matches the rank model, hostile
   inputs never crash, deterministic.
6. **Store referential integrity** — all deals resolve to real customers/reps; unknown IDs
   degrade to `None`/`[]`.
7. **Whole-pipeline determinism** — score every open deal twice → identical results.

### 14.2 Health score backtest (`scripts/backtest_health.py`)

A calibration harness that validates the health score against actual deal outcomes:

- Scores every **closed** deal (won = `WON_RANKS`, lost = `DEAD_RANKS`).
- Computes **AUC** — P(a lost deal scores riskier than a won deal); 0.5 = no signal, 1.0 = perfect.
- Produces a **calibration table**: for each band (and raw-score bucket), the actual loss rate.

On the synthetic seed this validates internal consistency (does the score separate the
outcome labels the generator baked in?). The same script is ready for real historical data —
the report layout is identical, making it the calibration tool for when SPR access arrives.

### 14.3 Grounding audit scripts

Three grounding audit scripts (`scripts/grounding_audit.py`, `grounding_audit4.py`,
`grounding_reaudit.py`) that run on the deterministic engine (no LLM) and check:

- **Cross-customer leakage** — does retrieval ever surface records from a different customer
  than the one in focus?
- **Prompt composition by source** — classifies every line of the commentary context into
  `customer_core / crm / deterministic_health / activity / quote_order / environment /
  similar_case_CROSS_CUSTOMER / corpus_playbook`, then reports the fraction of each type
  so we can audit how grounded each prompt is.
- **Structural origin classification** — distinguishes customer evidence (safe) from
  cross-customer analogies (labelled) from corpus/playbook content.

### 14.4 Contract checker (`scripts/check_contract.py`)

Hits every GET endpoint the web client calls via FastAPI's in-process `TestClient` and asserts
that the top-level keys the TypeScript types expect still exist. Runs in <1s with no GPU.

**Discipline enforced:** `docs/web-integration.md` documents the one-boundary rule:
"endpoint first, then `types.ts` → `api.ts` → `fixtures.ts` → component" — so the Python
engine and the Next.js app can never silently drift. `scripts/check_contract.py` is the
automated enforcement gate.

### 14.5 Live cache test (`scripts/live_cache_test.py`)

End-to-end test that drives the real bridge in-process via `TestClient`, parses the actual
SSE stream, and verifies that `context`/`cached` flags are set correctly and real tokens
stream from the LLM. Requires the model server on `:8765` (`SENPAI_USE_LLM=1`).

---

## 15. Test Suite

17 test files, **116 tests (1 skipped)**, all GPU-free.

17 test files, **116 tests (1 skipped)**, all GPU-free.

| File | What it covers |
|---|---|
| `test_scoring.py` | Deal health scoring engine |
| `test_flags.py` | Reliability flags |
| `test_manager_tools.py` | Manager tool set |
| `test_coach.py` | Review coach (lenses, absence reasoning) |
| `test_coaching_data.py` | Rep skill model + byte-stability + SPR anchors |
| `test_rep_profile.py` | Rep coaching profile generation |
| `test_progress.py` | Fiscal-year progress tracking |
| `test_briefing.py` | Morning briefing ranking + actions |
| `test_documents.py` | Proposal/ringisho PPTX/DOCX generation |
| `test_deals_search.py` | `find_deals` faceted search |
| `test_graph.py` | Knowledge graph construction + multi-hop queries |
| `test_semantic.py` | Hybrid retrieval (BM25, dense, RRF) |
| `test_knowledge.py` | Knowledge pipeline + confidence computation |
| `test_explainability.py` | Explainability module |
| `test_ingestion_persist.py` | Ingestion persist + overlay + cache invalidation |
| `test_research.py` | Research tool and grounding audit |
| `conftest.py` | Shared fixtures (`SENPAI_USE_LLM=0`, tmp overlay dirs) |

**New tests this week:** +18 coaching tests, +10 document tests, +8 graph/semantic tests, +6
briefing tests = **+42 new tests** since the start of Week 2.

---

## 15. Matsuda Context Prototype (`senpai/matsuda/`)

Distinct from the Account Intelligence engine (§4), the **Matsuda Context** is an earlier
prototype for a "synthesize once, answer many" customer-briefing pattern.

`build_account_context(customer_id) -> AccountContext` pulls all store data for a customer
once (activities, deals, scoring, flags, similar deals, playbook retrieval) into a single
persistent `AccountContext` object. Follow-up questions are then answered **purely from that
synthesized context** — no re-fetching. Key properties:

- Builds a retrieval log that records exactly which sources were consulted and how many rows
  were found (full auditability).
- `AccountContext.answer(question)` answers from the frozen context; `to_markdown()` produces
  an inspectable `report.md`.
- Hooked into `POST /api/coach/review` and `POST /api/coach/narrate`: requests containing
  "matsuda" or "松田" are intercepted and routed to the `MatsudaContext` engine instead of
  the normal LLM pipeline, avoiding the "NO MATCHING CUSTOMER" ambiguity issue.
- Streamlit demo: `senpai/apps/matsuda_demo.py` + `pages/4_Matsuda_Demo.py`.

---

## 16. Retrieval Observability — Retrieval Explorer

**`senpai/retrieval/trace.py`** is a per-turn observability buffer using Python's `ContextVar`
so concurrent requests never share state. Every retrieval surface (`notes_semantic`,
`knowledge_keyword`, `graph`) records into this buffer: source type, source ID, customer,
score, scope (`account:<id>` or `all`).

The API drains the buffer after each tool call and ships it to the UI as `tool` events in the
SSE stream.

**`web/components/assistant/retrieval-explorer.tsx`** is the UI surface — a collapsible
panel in the chat thread that shows for every turn:
- Which retrievers fired (`日報（意味検索）`, `社内ナレッジ（キーワード）`, `関係グラフ`)
- Scope: **account-scoped** (green badge, the trustworthy default) vs **all customers**
- Per-chunk detail: ID, customer name, score

This makes grounding **debuggable** — you can see exactly which chunks reached the model
and immediately spot cross-customer leakage.

---

## 17. Synthetic Dataset Expansion

The seed dataset was massively expanded to **FY2023–FY2026 historical data** (3 cohorts):
- **Live pipeline** (~140 deals): `order_rank` 2_A+…6_P, dated within 0–90 days of anchor
- **Historical won** (~280 deals): `1_Confirmed`, spread across prior fiscal years
- **Historical dead** (~100 deals): `7_Lost`/`8_Cancelled`

`store.open_deals()` filters to open ranks so the live dashboard stays bounded at ~140
even though the corpus is 520.

| File | Rows | What it is |
|---|---:|---|
| `deals.json` | **520** | Opportunity-level records |
| `sales_activities.json` | **2,337** | Activity log / daily reports |
| `quotes.json` | **480** | Quotes for progressed deals |
| `orders.json` | **280** | Order lines (confirmed/won deals) |
| `customers.json` | **150** | SMB customer master |
| `reps.json` | **24** | Sales reps (junior + senior, skill profiles) |
| `products.json` | 29 | Product master (major/mid/minor, pricing) |
| `environments.json` | 150 | Customer IT environment records |
| `playbook.json` | 31 | Coaching entries |
| `rank_history.json` | **1,612** | Order-rank change log (slip/regression detection) |
| `customer_aliases.json` | 150 | English/romaji alias forms |
| `coaching_threads.json` | 43 threads | Manager↔rep chat on flagged deals |

**Knowledge seed expanded:** `senpai/knowledge/seed/generated_items.json` grew from 12 → 177
coaching items (165 new items added — derived from the 11 validated senior principles).

Documented in `docs/synthetic_dataset.md` (new file this week).

---

## 18. Week-over-Week Summary

| Dimension | Week 1 (end) | Week 2 (end) |
|---|---|---|
| Tests | 30 passing | **116 passing (1 skipped)** |
| Tools | 18 | **38** |
| API endpoints | ~10 | **~20** |
| API latency (coaching) | ~7.5s | **~140ms (~54×)** |
| Synthetic dataset (deals) | 60 | **520 (3-year history)** |
| Synthetic dataset (activities) | 186 | **2,337** |
| Knowledge coaching items | 12 | **177** |
| Retrieval | Keyword/tag only | **BM25 + dense + RRF + knowledge graph (744 nodes)** |
| Document output | None | **PPTX + DOCX (4 tool variants)** |
| Coaching depth | Review Coach only | **Profile + progress + threads + explainability** |
| Account view | Deal-level only | **8-dimension account health + trajectory + expansion** |
| Workspace | Two separate pages | **Unified slash-command shell + artifacts + XLSX export** |
| Ingestion | None | **Audio/image/text → editable draft → overlay persistence** |
| Observability | None | **Retrieval Explorer (per-chunk source + scope + score)** |
| QA scripts | 0 | **5 (stress pipeline, health backtest, grounding audit ×3, contract checker, live cache test)** |

---

## Appendix A — New Files This Week

| Path | What it is |
|---|---|
| `senpai/account/` | Account Intelligence engine (health, trajectory, expansion, summary, context) |
| `senpai/briefing.py` | Morning briefing — urgency-ranked action worklist |
| `senpai/coach/profile.py` | Rep coaching profile (1:1 brief, weaknesses, strengths) |
| `senpai/coach/progress.py` | Fiscal-year progress + coaching acted-on rate |
| `senpai/coach/explainability.py` | Coaching explainability (triggers, evidence, outcome stats) |
| `senpai/growth.py` | Growth / Motivation portal (5 transparent skill scores) |
| `senpai/documents/` | Document generation (proposal, ringisho, author, context, render, registry, narrative) |
| `senpai/retrieval/` | Hybrid semantic search (build_index, semantic, deals, knowledge, playbook, **trace**) |
| `senpai/retrieval/trace.py` | Per-turn retrieval observability buffer (ContextVar) |
| `senpai/graph/` | Knowledge graph (build, query) |
| `senpai/ingestion/` | Multimodal ingestion (pipeline, multimodal, persist) |
| `senpai/tools/gcal.py` | Google Calendar integration (two-step confirm) |
| `senpai/matsuda/` | Account context synthesis prototype — synthesize-once, answer-many |
| `senpai/apps/matsuda_demo.py` | Streamlit demo for Matsuda Context |
| `web/components/workspace/` | Workspace shell (workspace, slash picker, artifact-card, unified ArtifactBody, cards/) |
| `web/components/account/` | Account Intelligence frontend (accounts-index, account-view) |
| `web/components/assistant/retrieval-explorer.tsx` | Retrieval Explorer — per-chunk grounding debugger |
| `web/components/coaching/rep-profiles.tsx` | Rep coaching profiles frontend (372 lines) |
| `web/lib/artifact-export.ts` | Client-side XLSX export (two-sheet: brief + sources) |
| `web/lib/artifacts.ts` | Artifact type definitions and pure assemblers |
| `web/public/logo.png` | Senpai brand logo |
| `web/components/site/brand.tsx` | Brand component |
| `scripts/stress_pipeline.py` | 7-probe robustness harness (§14.1) |
| `scripts/backtest_health.py` | Health score calibration / AUC backtest (§14.2) |
| `scripts/grounding_audit.py` | Cross-customer leakage + prompt composition audit (§14.3) |
| `scripts/grounding_audit4.py` | Structural grounding classification (§14.3) |
| `scripts/grounding_reaudit.py` | Grounding re-audit (updated version) |
| `scripts/live_cache_test.py` | Live SSE cache correctness test (§14.5) |
| `scripts/check_contract.py` | Web ↔ engine contract checker (§14.4) |
| `scripts/eval_intent_router.py` | Atlas feasibility eval (§12.2) |
| `scripts/bench_synthesis.py` | Model decomposition A/B with frozen tool context (§12.3) |
| `scripts/bench_synthesis_results.json` | Round 1 benchmark results (27B vs 8B-bf16) |
| `docs/synthetic_dataset.md` | Synthetic dataset reference (3-year time model, row counts) |
| `docs/web-integration.md` | Web ↔ engine integration pattern + contract discipline |
| `docs/phase25_session_log.md` | Phase 2.5 session log (latency, evals, bugs, features) |
| `docs/accounts.md` | Account Intelligence reference |
| `docs/coaching.md` | Coaching platform reference |
| `docs/retrieval.md` | Retrieval reference |
| `docs/resolution_and_routing.md` | Customer resolution + reasoning router reference |
| `docs/workspace.md` | Workspace shell reference |
| `docs/llm_bridge.md` | LLM bridge + SSE protocol reference |
| `docs/README.md` | Documentation index |

## Appendix B — Run Commands

```bash
export SENPAI_TODAY=2026-06-16

# Python app (no GPU)
.venv/bin/streamlit run senpai/apps/manager_dashboard.py   # dashboard :8501
.venv/bin/streamlit run senpai/apps/matsuda_demo.py        # Matsuda demo

# Web app (combined launcher)
SENPAI_TODAY=2026-06-16 bash scripts/run_web.sh            # bridge :8000 + frontend :3000
# Or separately:
SENPAI_TODAY=2026-06-16 uvicorn senpai.api.server:app --port 8000
cd web && npm install && npm run dev

# Document generation (no GPU)
python -m senpai.documents.proposal D001
python -m senpai.documents.ringisho D001

# Build retrieval index
SENPAI_TODAY=2026-06-16 python -m senpai.retrieval.build_index

# Verify (no GPU)
.venv/bin/pytest tests/

# QA scripts (no GPU, no network)
SENPAI_TODAY=2026-06-16 python scripts/stress_pipeline.py
SENPAI_TODAY=2026-06-16 python scripts/backtest_health.py
SENPAI_TODAY=2026-06-16 python scripts/check_contract.py
SENPAI_TODAY=2026-06-16 python scripts/grounding_audit.py

# Offline evals
python scripts/eval_intent_router.py
python scripts/bench_synthesis.py --candidate-base http://127.0.0.1:8766/v1 \
       --candidate-model qwen3-8b --queries 4
```
