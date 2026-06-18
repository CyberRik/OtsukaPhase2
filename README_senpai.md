# Senpai — Sales Knowledge & Deal-Health Copilot (Phase 2)

Senpai turns the Phase-1 tool-calling model (**exp3**) into a usable product with
**three front ends over one shared engine**:

- **Junior assistant** (Gradio chat) — pre-call briefs, in-the-moment playbook
  answers, daily-report drafting, expert routing, and the **Sales Review Coach**
  (below). The human, relatable story.
- **Manager assistant** (Gradio chat) — ask the team pipeline in words: which deals
  are at risk, a digest of everyone's reports, who needs coaching, draft a nudge.
- **Manager dashboard** (Streamlit) — the team pipeline with red/yellow/green deal
  health and report-reliability flags. The business-impact layer.

Both chats also have a `web_search` tool (Tavily when `TAVILY_API_KEY` is set, canned
fallback otherwise) so they double as a normal assistant for ad-hoc research.

Two onboarding capabilities sit on top of the same engine:

- **Sales Review Coach** (`senpai/coach`, chat tool + Streamlit page) — paste a raw
  meeting note or daily report and get a senior rep's *reasoning scaffold*: what
  they'd notice, what's missing, risk signals, the questions they'd ask next,
  several possible next moves, and the decision factors. It **teaches reasoning —
  it never returns a single "correct answer."**
- **Knowledge expansion pipeline** (`senpai/knowledge`) — turns real interview
  transcripts into validated principles, then GenAI-illustrated coaching scenarios,
  with **full provenance and a human approval gate**. No synthetic expertise: the
  Coach only ever surfaces human-approved, interview-traceable advice.

The shared core is a **hybrid deal-health scorer**: deterministic Python produces the
score and the reasons (trustworthy, GPU-free, never hallucinates a number); exp3 only
*narrates* the "why". **If the model server is down, narration degrades to a templated
string and the dashboard/scoring are unaffected.**

```
senpai/data/store.py  ── single source of truth (seed JSON)
        │
        ├─ health/{scoring,flags}.py ── deterministic, no GPU ──┐
        ├─ retrieval/playbook.py                                │
        ├─ coach/review.py          ── Sales Review Coach engine│
        ├─ knowledge/{schema,store,generate,review}.py ── KX    │
        ├─ tools/{schemas,impl}.py  ── dispatch(), never raises │
        └─ llm/{client,narrate}.py  ── exp3 + templated fallback│
                                                                │
   apps/manager_dashboard.py (Streamlit, GPU-free) ◄───────────┤
   apps/review_coach.py      (Streamlit, GPU-free) ◄───────────┤
   apps/knowledge_review.py  (Streamlit, GPU-free) ◄───────────┤
   apps/junior_chat.py       (Gradio, needs exp3)  ◄───────────┘
```

### Sales Review Coach (`senpai/coach`)

Deterministic at the core: a set of **lenses** encodes a senior's mental checklist
(decision-maker, timeline, criteria, next step, budget). Each lens fires when its
cues are *absent* from the note — the gap a junior tends not to see — and emits an
observation + missing-info + question + risk + decision-factor. Presence detectors
add stall-language and competitor factors. When a `deal_id` is supplied, the
existing `score_deal`/`deal_flags` signals are fused in. exp3 only *rephrases* the
findings (`narrate_review`); with the server down it falls back to the
deterministic render. Exposed as the `review_sales_note` junior-chat tool and the
`review_coach.py` page.

### Knowledge expansion pipeline (`senpai/knowledge`)

Three immutable layers that may only derive *down*, never invent *up*:

```
Layer 0  Source     raw interview / survey            (immutable, cited by span)
Layer 1  Principle  a human-VALIDATED claim           (candidate → approved)
Layer 2  Item       a GenAI-illustrated scenario      (draft → approved gate)
```

GenAI is given an approved principle **only** and may illustrate it into a
scenario; a `ground_check` pre-screen rejects invented numbers / missing
alternatives, and nothing reaches a junior until a human approves it in the review
console. Confidence is **computed, not authored** (2 interviews → `high`, 1 →
`low`/`medium`); an unapproved or grounding-failed item is `unverified` and never
shown. Every item stores its `principle_id`, `interview_ids`, generator model,
prompt version, and reviewer — provenance is never broken.

## Setup

```bash
.venv/bin/pip install -r requirements.txt      # adds streamlit, pandas, pytest
```

The model is *served* by the external vLLM venv (same as the demo); nothing to install
there. The dashboard and tests need **none** of that — they are pure Python.

## Run

```bash
# Manager dashboard — no GPU, no model server needed
.venv/bin/streamlit run senpai/apps/manager_dashboard.py     # http://localhost:8501

# Sales Review Coach — paste a note, get a senior's reasoning (GPU-free; exp3 optional)
.venv/bin/streamlit run senpai/apps/review_coach.py

# Knowledge review console — generate scenarios from principles & approve them (GPU-free)
.venv/bin/streamlit run senpai/apps/knowledge_review.py

# Chats — need exp3 served
./scripts/serve_model.sh                                      # exp3 on :8765 (needs GPU)
.venv/bin/python senpai/apps/junior_chat.py                  # junior  → http://localhost:7860
.venv/bin/python senpai/apps/manager_chat.py                 # manager → http://localhost:7861
```

Both chats share the exp3 server; they listen on different ports (7860 / 7861) so you
can run them side by side. The manager chat is scoped to manager tools
(`list_at_risk_deals`, `team_pipeline_overview`, `team_report_digest`,
`rep_coaching_focus`, `draft_message`, `query_spr`, `score_deal_health`, `web_search`);
the junior chat keeps its coaching tools plus `review_sales_note` and `web_search`.

### Optional: real web search

`web_search` returns canned (Japanese) results offline. For live results, put
`TAVILY_API_KEY=...` in a repo-root `.env` (loaded automatically) — same mechanism as the
Phase-1 demo.

Sanity-check the server before the chat demo:

```bash
curl -s localhost:8765/v1/models | python3 -m json.tool      # should list "exp3"
```

### Reproducible demo dates

The committed seed data is anchored to **2026-06-16**. To pin scoring's "today" to that
anchor (so the same deals show the same bands regardless of the real date):

```bash
export SENPAI_TODAY=2026-06-16
```

## Data

`senpai/data/seed/*.json` is synthetic, bilingual (Japanese content), and **committed** so
everything runs with zero setup. Regenerate deterministically with:

```bash
python -m senpai.data.gen_seed       # byte-stable; re-running leaves git clean
```

It seeds ~8 reps, ~35 SMB customers, ~60 deals, ~25 playbook entries, environments and
daily reports — including **4 deliberately dead/dying deals** (D001–D004) so the dashboard
flags real risk on first load.

### Interview-derived knowledge (`senpai/knowledge/seed/`)

Separate from the synthetic deal data, this holds the **real** extracted knowledge:

- `sources.json` — the interview/survey respondents (`I01`, `I02`).
- `principles.json` — **11 validated-candidate principles** extracted from 2 senior
  respondents × 7 reasoning scenarios; each cites the exact sentence a senior wrote.
  4 are backed by *both* respondents (→ `high` confidence once approved).
- `generated_items.json` — human-curated Layer-2 coaching scenarios (draft, awaiting
  approval).

Principles ship as `status: candidate` on purpose — they become visible to juniors
only after a human approves them in the review console. See
`docs/knowledge_extraction.md` for the extraction worksheet and the 2-interviews →
10–20-principles process.

## Verify (no GPU)

```bash
.venv/bin/pytest tests/                          # 40 tests: scoring, flags, coach, knowledge
.venv/bin/python -m senpai.tools.impl            # one canned call per tool
python -m senpai.data.gen_seed && git diff --exit-code senpai/data/seed/   # reproducible
```

`tests/test_coach.py` locks the Coach's teaching behaviour (surfaces gaps, never
collapses to one answer); `tests/test_knowledge.py` locks the pipeline guarantees
(confidence is earned not authored, grounding rejects invented specifics, only
approved + traceable items reach the Coach).

## PM demo run sheet

1. **Lead with the human story.** Open the **junior chat** and run:
   - 「明日アクメ商事に訪問。準備をお願い」 → pulls the deal, playbook tactics, the
     customer's IT environment, and the deal-health read in one brief.
   - 「お客様が決定を先延ばしにします。先輩ならどうしますか？」 → an attributed senior
     tactic (or an expert hand-off if the playbook is thin).
   - 「今日の活動から日報を作成して…」 → an SPR-ready draft.
2. **Switch to business impact.** Open the **manager dashboard** and:
   - Point at the KPI row (🔴 at-risk count, flagged reports).
   - Sort the pipeline by health and drill into **D001** — show the signal-by-signal
     breakdown and the manager flag + suggested action.
   - Scroll to the **report-reliability panel**: "these deals say one thing but the data
     says another — that's the three dead deals we flag in week one."
3. **Show the onboarding angle (Sales Review Coach).** Open the **junior chat** (or the
   `review_coach.py` page) and paste a thin note — 「お客様は社内で検討してから連絡する
   とのこと」. It returns a senior's reasoning scaffold (notices / missing info / risks /
   questions / *several* possible next moves / decision factors), not one prescribed
   answer. The teaching, not-flashy, core.
4. **Show the anti-synthetic knowledge story.** Open the **knowledge review console**.
   Point at the 11 principles extracted from 2 real senior respondents, each traceable to
   the exact sentence they wrote; 4 confirmed by *both* seniors. Approve one (e.g. P008 +
   item G0001) and watch the Coach start citing 「先輩の知見 (出典 I01・I02 / 確度 high)」.
   The headline: *zero invented advice — everything traces to an interview.*
5. **Show it never breaks.** Stop the model server and reload the dashboard: narration
   falls back to a templated reason; scoring, flags, and the Coach are unchanged.

Same engine, three audiences: the junior's pre-call brief, the junior's review coaching,
and the manager's risk view are the *same* deterministic reads, phrased for each.
