# Senpai — Progress Report
### Internship Week 5 · Phase 2, Week 1 · June 2026
**Team:** AI Department (intern team) · **Audience:** Manager / mentors / Givery team
**Project:** Senpai — Sales Knowledge & Onboarding Copilot for Otsuka Shokai

---

## 0. Executive summary

Senpai makes the knowledge that lives in Otsuka's best salespeople available to every rep —
**on demand and in the context of a specific customer and deal** — while giving managers one
place to read deal health and catch dying deals early. It is a fine-tuned, tool-calling
assistant anchored to Otsuka's **real SPR data**, not a generic sales chatbot.

This week we:

1. **Locked the theme and validated it** against a published research review *and* **two real
   interviews with Otsuka Shokai senior salespeople**.
2. **Built a working end-to-end prototype** of both the junior assistant and the manager
   dashboard + deal-health engine, on synthetic data authored in Otsuka's **real SPR schema**
   (so it is production-ready the moment we get data access).
3. Started **two parallel UX surfaces** — a Python app and a web app — to test fast and keep
   the one that lands best.
4. Began the **anti-synthetic knowledge pipeline**: 11 senior principles extracted from the
   two interviews, each traceable to the exact sentence a senior wrote.

The rest of this document is the full record — nothing omitted.

---

## 1. The problem we selected, and how it arose

### 1.1 Where it came from
From interviews and a structured Q&A with sales staff (incl. Akiyama-san) two pain points
surfaced again and again:

- **New salespeople ramp slowly.** The knowledge that matters most — how to research a
  customer, what to say, how to read a deal, how to handle a specific situation — lives in the
  heads of senior reps and is transferred informally (asking seniors, study sessions, the
  trainer–trainee system). **No system captures it or delivers it at the moment a junior needs
  it.**
- **Nobody can reliably tell whether a deal is real.** Reports are written but not believed;
  stated close dates slip silently; dead deals sit in the pipeline unflagged. The single
  biggest delay is from "closing" to a final decision — reps sit on deals that are already
  dying and nobody catches it early. Even experienced reps misjudge close likelihood.

So we framed Senpai as **one system serving two users**:
- **Junior reps** — senior knowledge on demand, in context (the relatable, human face).
- **Managers / seniors** — a single view to mentor, review, and spot risk (the harder
  technical core that produces visible value every day).

### 1.2 Why it is relevant for Otsuka specifically
- Otsuka's targets are **~78% small companies with little or no web presence**, so automated
  web research does *not* solve the problem — the value must come from **internal SPR history
  and real senior reasoning**, which Senpai is built around.
- Japan already has a strong but informal apprenticeship engine (OJT, senpai–kōhai). The gap
  is **externalisation** — turning tacit know-how into reusable, in-the-flow guidance. That is
  exactly where conversation analysis + summarisation add value, and Senpai is positioned to
  *augment the senpai*, not replace the human relationship.
- The same captured deal/report data that powers onboarding also powers **deal-health scoring
  and report-reliability flags** for managers — build the capture layer once, serve both.

---

## 2. Manager feedback and the President's three growth factors

> *"I think this is a very strong theme based on real sales activities. It addresses practical
> business challenges and has the potential to provide value to both new sales representatives
> and managers. In addition, our company president often emphasizes three key factors that
> drive the company's growth: **Knowledge, Motivation, Experience**. I would appreciate it if
> these concepts could be incorporated throughout the system design and implementation."*

We have made these three factors the **design spine** of Senpai. Every feature maps to at
least one, and the system as a whole is a growth loop across all three:

| Growth factor | What it means here | How Senpai delivers it |
|---|---|---|
| **Knowledge** | Sharing senior salespeople's know-how and best practices | The **playbook** + **Knowledge pipeline**: attributed senior tactics surfaced in context (`retrieve_playbook`), and the Sales Review Coach that makes a senior's *reasoning* explicit. Every piece of advice is traceable to a named senior. |
| **Experience** | Learning from past deals, proposals, and successful cases | The **SPR mining** core: `query_spr`, `find_similar_deals`, and the deal-health engine learn from what reps *actually did and how it ended* — won deals, stage transitions, timing — so a junior facing a new customer sees analogous real cases, not generic advice. |
| **Motivation** | Supporting growth through coaching, feedback, and visibility into personal progress | **Coaching + feedback + visibility**: the Review Coach gives in-the-flow feedback; `route_to_expert` keeps a junior unblocked and connected to a mentor; the manager dashboard + `rep_coaching_focus` give visibility into where each rep needs support — turning oversight into encouragement, not surveillance. |

**The loop:** Knowledge (senior know-how) is captured → applied to a junior's real situation as
Experience (past deals) → reinforced through coaching and visible progress, which builds
Motivation → which produces better-documented deals → which feeds the Knowledge base again.
That virtuous cycle is the "drive growth" the President describes, made operational.

---

## 3. The solution proposal (current scope)

One shared, deterministic engine serves two audiences.

### 3.1 For the salesperson (junior assistant)
Natural-language chat that grounds every answer in Otsuka data and **routes to a human expert
when it isn't confident** (a first-class feature, not a fallback). Core flows:

- **Pre-call preparation** — pull the customer's SPR history (or similar past deals if new),
  relevant senior tactics, product/environment details, and seasonal timing → a one-screen brief.
- **In-the-moment question** — "customer keeps delaying — what do seniors do here?" → an
  attributed senior tactic, or an expert hand-off if the playbook is thin.
- **Report drafting** — turn logged activity into an SPR-ready daily-report draft to edit.

**Junior tool set (10):** `query_spr`, `find_similar_deals`, `retrieve_playbook`,
`lookup_customer_environment`, `get_product_info`, `score_deal_health`, `draft_daily_report`,
`route_to_expert`, `get_seasonal_context`, `web_search`.

### 3.2 For the manager (dashboard + assistant)
A single cross-team view plus a chat to ask the pipeline in words.

- **Manager dashboard** — team pipeline table with 🔴🟡🟢 **deal-health** chips, drill-down
  (signal-by-signal breakdown + suggested action), and a **report-reliability panel** that
  surfaces deals whose recorded status contradicts their activity signals.
- **Manager assistant (chat)** — "which deals are at risk, by rep?", a digest of everyone's
  reports, who needs coaching, draft a nudge.

**Manager tool set (8):** `query_spr`, `score_deal_health`, `list_at_risk_deals`,
`team_pipeline_overview`, `team_report_digest`, `rep_coaching_focus`, `draft_message`,
`web_search`.

### 3.3 The technical core — the deal-health engine
The engine underneath both surfaces is a **hybrid scorer**: deterministic Python produces the
score and the reasons (trustworthy, GPU-free, never hallucinates a number); the fine-tuned
model only *narrates* the "why" and drives the chat. If the model server is down, narration
degrades to a templated string and scoring/flags are unaffected.

It reads only **real SPR fields** and produces a 0–100 risk score → 🔴 ≥55 / 🟡 25–54 / 🟢 <25,
with a Japanese reason for every signal:

| Signal | Source field(s) |
|---|---|
| Staleness | latest `sales_activities.activity_date` vs the deal's rank cadence |
| Rank stagnation | `rank_updated_at` vs the `order_rank` benchmark |
| Order date passed | `days_until_order` / `expected_order_date` |
| Rank regression | `order_rank` vs `initial_order_rank` |
| Missing decision-maker | `sales_activities.business_card_info` (title) |
| Stall language | latest `sales_activities.daily_report` (JP stall lexicon) |
| Low activity | gap in `sales_activities.activity_date` |

**Report-reliability flags:** `close_date_passed`, `stale_active`, `missing_fields`,
`optimism_mismatch` (a strong `order_rank` but red health — the rep's report says one thing,
the data says another), `unsupported_rank`.

---

## 4. Research validation (the status-quo report)

We commissioned/compiled a research review (`SalesKnowledgeReport.pdf`) of global and Japanese
best practice. It independently validates the theme:

- **Ramp time is the headline metric and it is long.** ~3 months to be "customer-ready" but
  **~9 months to competence and ~15 to top performance** for complex B2B; replacing a high
  performer can cost **>$200k**. Structured onboarding cuts ramp by up to ~50%.
- **Tacit knowledge is the real problem and it's hard.** Top performers' advantage is
  *procedural, contingent, adaptive* knowledge they often can't articulate. Generic knowledge
  bases fail (storage ≠ enablement; reps won't context-switch to search; content goes stale).
  What works: **real-call libraries, win/loss analysis, structured mentorship, and in-moment,
  trigger-based delivery** — exactly Senpai's design.
- **Japanese CI adopters have repeatedly halved onboarding** by turning real deals and
  top-performer calls into structured training (MiiTel/アドプランナー, ailead/メリービズ,
  amptalk/ビザスク — multiple **8→3 month / ~50%** cases). This is our north-star benchmark.
- **Deal-health / forecast scoring is a real, adjacent capability** (Clari, Gong, Aviso,
  BoostUp) that **runs on the same captured data as onboarding** — confirming our "build the
  capture layer once, serve both" architecture.
- **Caveat we carry honestly:** vendor figures are self-reported and outcomes depend on
  recording coverage + manager coaching, not technology alone. We treat them as directional.

---

## 5. Real interviews with Otsuka Shokai salespeople

Because tacit knowledge cannot be self-reported through generic surveys, we ran a
**forced-choice + reasoning** elicitation with **two senior Otsuka Shokai salespeople**:

- **Format:** a common questionnaire (`Q01`) — 10 open questions (problem discovery) + **7
  two-choice scenarios** where each senior picks A/B **and explains why**.
- **Respondents:** `I01` (senior A) and `I02` (senior B), June 2026. 2 seniors × 7 scenarios =
  **14 tacit-judgment data points** — not "two thin interviews."
- **Why this format:** the "why" exposes the **decision factor** a junior can't see; agreement
  between seniors → a high-confidence principle; divergence → a built-in *alternative
  viewpoint* that teaches judgment, not rules.

**Result: 11 validated senior principles, 4 backed by *both* seniors independently** — every
one traceable to the exact sentence a senior wrote. Examples:

- *P001* — Before widening the deal with a new proposal, settle the current deal's certainty
  and decision timing (R1+R2 → **high**).
- *P006* — A 部長 won't sign until the IT person is satisfied; win over the on-site technical
  contact (R1+R2 → **high**).
- *P008* — A first visit is relationship-building before information-gathering; hear the
  business and concerns, not just specs (R1+R2 → **high**).
- *P011* — Asking a decision-maker to join depends on timing and relationship; a sudden ask
  backfires (R1+R2 → **high**).

These principles feed a provenance-preserving pipeline (Source → validated Principle →
GenAI-*illustrated* coaching item → human approval gate). Confidence is **computed, not
authored** (2 sources → high). The headline: **zero invented advice — everything traces to an
interview.** Full method and the principle table are in
[`knowledge_extraction.md`](knowledge_extraction.md).

We also **used these real insights to generate richer synthetic data** (stall phrases, customer
challenges, decision-maker patterns) so the prototype behaves like real Otsuka deals.

---

## 6. Data strategy — production-ready before we have the data

We do **not** yet have access to live SPR data. But we obtained the **real SPR schema and
column headers** (4 tables, documented in [`../Schema.md`](../Schema.md)):

- `deals` — opportunity-level: `order_rank` (`1_Confirmed … 8_Cancelled`), financials, expected
  order date.
- `sales_activities` — the interaction log: `activity_date`, `daily_report`,
  `business_card_info`, `customer_challenge`.
- `quotes` — pricing, discounts, `similar_quote_count`, expiry.
- `orders` — realised order lines, gross profit, supplier.

**So we wrote the entire pipeline against this real schema**, and generate **byte-stable
synthetic data in exactly this shape** (`senpai/data/gen_seed.py`). The deal-health signals,
tools, and dashboard all read the real field names (`order_rank`, `expected_order_date`,
`daily_report`, …). **The day we get SPR access, we replace the synthetic seed with the real
export and nothing else changes — it is a drop-in.**

Current synthetic dataset: 8 reps, 35 SMB customers, 60 deals (37 live pipeline), ~186 sales
activities, ~50 quotes, ~19 orders, 25 playbook entries — with 4 deliberately dead-but-
optimistic deals so the dashboard flags real risk on first load (the "flag the dead deals in
week one" story).

One known **gap**: customer IT-environment data (PC/network) is not in the four SPR tables — we
flag it as an open question for the data owner.

---

## 7. Current build status — two prototype surfaces, tested in parallel

We are deliberately **prototyping fast and validating feature ideas** before committing to one
UX. We currently run the *same engine* behind **two front-end surfaces** and will keep whichever
lands best with users:

### 7.1 Python app (Streamlit + Gradio)
The fastest path to demoable, GPU-free surfaces:

- **`senpai/apps/manager_dashboard.py`** (Streamlit) — the team deal-health dashboard (KPIs,
  pipeline table with health chips, drill-down, reliability panel). Runs with **no GPU**.
- **`senpai/apps/junior_chat.py`** (Gradio, port 7860) — the junior assistant chat.
- **`senpai/apps/manager_chat.py`** (Gradio, port 7861) — the manager assistant chat.
- **`senpai/apps/Home.py` + `pages/`** (Streamlit multipage) — Deal Health, Review Coach,
  Knowledge Review consoles for internal testing.
- Both chats drive a tool-calling loop over the fine-tuned model (exp3) with a `web_search`
  tool, and degrade gracefully when the model server is offline.

### 7.2 Web app (Next.js + FastAPI)
A production-quality UX exploration that presents Senpai as a **knowledge-transfer & onboarding
platform** (not a generic chatbot — an "intelligence dossier" aesthetic):

- **Backend:** `senpai/api/server.py` — a thin **FastAPI bridge** exposing the existing engines
  as JSON (`/api/dashboard`, `/api/deals/{id}`, `/api/coach/review`, `/api/knowledge/*`). It
  changes no engine logic; it only reshapes results for the frontend.
- **Frontend:** `web/` — Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui. Pages:
  - `/` — what Senpai is (the three-layer trust model + stats).
  - `/coach` — Sales Review Coach: paste a note → six lenses of senior reasoning.
  - `/knowledge` — Knowledge Explorer: principles, **verbatim interview provenance**,
    computed-confidence badges, derived items.
  - `/dashboard` — Manager Dashboard: deal-health, reliability flags, drill-down.
  - Separate `junior` and `manager` route groups.
- If the API is offline the UI degrades to a committed seed snapshot — it never shows a broken
  screen. Full design spec in `web/DESIGN.md`.

### 7.3 Why two
The engine is settled and shared; the **open question is UX and adoption** (the report is clear
that tools fail on workflow friction, not features). Running a Python prototype (fast iteration)
and a polished web prototype (production feel) in parallel lets us **test which surface reps and
managers actually use**, then converge. The two are decoupled and can run independently.

---

## 8. What's working today (verification)

- **Deterministic engine + tools are fully working and tested**, GPU-free:
  - `pytest tests/test_scoring.py tests/test_flags.py tests/test_manager_tools.py` → **22
    tests pass**; the coach engine adds **8 more** (30 total green).
  - `python -m senpai.tools.impl` exercises one canned call per tool and prints grounded
    Japanese output.
- **Manager dashboard runs with no GPU** and flags the seeded dead deals (D001–D004) on first
  load.
- **Both chats run** against the served model; the web app's FastAPI endpoints return valid
  data (`/api/dashboard`, `/api/deals/D001`, `/api/coach/review`).
- **Seed regeneration is byte-stable** (reproducible demos), anchored to 2026-06-16 via
  `SENPAI_TODAY`.
- The deal-health engine and chats are **isolated** from the experimental surfaces, so a problem
  in one prototype cannot break the other.

---

## 9. Success metrics we will report against

- Time-to-productivity / research-prep time for new hires (before vs after, on real anonymised
  cases).
- Report-drafting time saved per rep per day.
- Share of junior questions resolved in-context vs routed to a human (and routing accuracy).
- Manager time spent reviewing reports; number of at-risk deals surfaced early.
- Qualitative: junior confidence and senior-mentor load.

For the internship evaluation specifically: a **before/after on a small number of real
(anonymised) cases** to produce a concrete impact story.

---

## 10. Risks, open dependencies, and next steps

**Critical dependency — SPR data access.** The pipeline is built against the real schema and is
production-ready on access. Until then we run on schema-accurate synthetic data.

**Questions for the data owner (sent / to confirm):**
- Full `order_rank` *history* (not just first + latest), needed for slip/regression detection.
- How `order_rank` is assigned (rep-manual vs rule-based).
- `daily_report` fill-rate and length (it's our knowledge-mining corpus).
- `opportunity_id` ↔ `deal_id` cardinality.
- Where customer IT-environment data lives (the one schema gap).
- Anonymisation rules for a pilot.

**Next steps (Week 6+):**
1. Converge the two UX surfaces based on quick user feedback.
2. Expand the validated knowledge base (more interviews / promote conditional sub-principles).
3. Run a before/after on a small set of anonymised cases once data access is scoped.
4. Continue mapping every new feature to **Knowledge / Experience / Motivation**.

---

## Appendix A — repository map

| Path | What it is |
|---|---|
| `senpai/` | The pipeline: deal-health engine on the real SPR schema + junior/manager chats + manager dashboard |
| `senpai/data/gen_seed.py`, `senpai/data/seed/` | Synthetic data in the real SPR shape (`deals`, `sales_activities`, `quotes`, `orders` + reference data) |
| `senpai/health/`, `senpai/tools/`, `senpai/llm/` | Scoring/flags, tool surface, model client |
| `senpai/api/` + `web/` | The Next.js web-app prototype + its FastAPI bridge |
| `senpai/coach/`, `senpai/knowledge/` | Sales Review Coach + the provenance-preserving knowledge pipeline |
| `Schema.md` | The real Otsuka SPR schema + how the pipeline maps to it |
| `docs/knowledge_extraction.md` | The 2-interview → 11-principle extraction method |
| `demo/` | The Phase-1 tool-calling demo that proved the fine-tuned model |

## Appendix B — run commands

```bash
export SENPAI_TODAY=2026-06-16

# Python app
.venv/bin/streamlit run senpai/apps/manager_dashboard.py     # dashboard (no GPU) :8501
./scripts/serve_model.sh                                      # exp3 model :8765 (GPU)
.venv/bin/python senpai/apps/junior_chat.py                  # junior chat :7860
.venv/bin/python senpai/apps/manager_chat.py                 # manager chat :7861

# Web app
SENPAI_TODAY=2026-06-16 uvicorn senpai.api.server:app --port 8000   # API bridge
cd web && npm install && npm run dev                                # frontend :3000

# Verify (no GPU)
.venv/bin/pytest tests/test_scoring.py tests/test_flags.py tests/test_manager_tools.py
```
