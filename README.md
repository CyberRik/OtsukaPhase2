# Senpai — Sales Knowledge & Onboarding Copilot (Otsuka, Phase 2)

Senpai makes the knowledge that lives in Otsuka's best salespeople available to every rep —
on demand and in context — while giving managers one place to read deal health and catch
dying deals early. It is a **fine-tuned, tool-calling assistant (exp3)** anchored to Otsuka's
real SPR data, not a generic sales chatbot.

The pitch in one line: **onboarding is the relatable face; pipeline reliability — "nobody
knows if a deal is real" — is the engine underneath.** The same deterministic deal-health
read that briefs a junior before a call also flags a manager's dying deal.

---

## Repository map

| Path | What it is | Owner |
|---|---|---|
| **`senpai/`** | **Our pipeline** — the deterministic deal-health engine on Otsuka's real SPR schema, plus the junior chat, manager chat, and manager dashboard. **Start here.** | this team |
| `Schema.md` | The real Otsuka SPR schema (4 tables) + how our pipeline maps to it | this team |
| `senpai/api/`, `web/`, `senpai/coach/`, `senpai/knowledge/` | A separate, in-progress **web-app experiment** (FastAPI + Next.js frontend, Sales Review Coach, Knowledge Explorer) | another team member |
| `demo/` | Phase-1 tool-calling demo (the exp3 Gradio showcase that proved the model) | this team |

> Our pipeline does **not** import or depend on the web-app experiment; the two are
> decoupled and can run independently. See `senpai/README.md` → *Isolation* for details.

---

## Quickstart (our pipeline)

```bash
# install client-side deps into the project venv
.venv/bin/pip install -r requirements.txt
export SENPAI_TODAY=2026-06-16        # pin scoring's "today" to the seed anchor

# Manager dashboard — no GPU, no model server needed
.venv/bin/streamlit run senpai/apps/manager_dashboard.py     # http://localhost:8501

# Chats — need the exp3 model served (GPU)
./scripts/serve_model.sh                                     # exp3 on :8765
.venv/bin/python senpai/apps/junior_chat.py                  # junior  → http://localhost:7860
.venv/bin/python senpai/apps/manager_chat.py                 # manager → http://localhost:7861
```

The deal-health engine, dashboard, and unit tests are **pure Python (no GPU)**; only the two
chats need the model server. The model itself is served by the external vLLM venv (see
`scripts/serve_model.sh`), the same one the Phase-1 demo uses.

**→ Full engineering reference, tool list, env vars, and verify steps:
[`senpai/README.md`](senpai/README.md).**
**→ The data shape we build against: [`Schema.md`](Schema.md).**

---

## What's inside the pipeline (at a glance)

- **Real SPR schema.** `senpai/data/gen_seed.py` generates byte-stable synthetic data in
  Otsuka's production shape (`deals`, `orders`, `quotes`, `sales_activities`), so the real
  data is a drop-in when we get access. `order_rank` (`1_Confirmed … 8_Cancelled`) is the spine.
- **Deterministic deal-health engine.** Seven rank-aware signals (staleness, rank stagnation,
  order-date passed, rank regression, missing decision-maker, stall language, low activity) →
  a 🔴🟡🟢 score with a Japanese reason for every signal. No number is ever invented by a model.
- **Report-reliability flags.** Surfaces deals whose recorded rank contradicts their activity
  signals (`optimism_mismatch`, `stale_active`, `close_date_passed`, …).
- **Two chats + a dashboard.** Junior assistant (briefs, playbook, report drafting, expert
  routing), manager assistant (at-risk deals, report digests, coaching focus, drafting), and a
  Streamlit dashboard — all over one shared engine, with a `web_search` tool on both chats.

## Verify (no GPU)

```bash
export SENPAI_TODAY=2026-06-16
.venv/bin/pytest tests/test_scoring.py tests/test_flags.py tests/test_manager_tools.py
.venv/bin/python -m senpai.tools.impl        # one canned call per tool
```

## Phase-1 demo

The original tool-calling showcase (exp3 answering in natural language while calling real
tools) lives in [`demo/`](demo/) with its own run sheet at `demo/demo_script.md`.
