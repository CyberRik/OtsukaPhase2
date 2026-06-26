# Senpai — documentation index

Senpai is a grounded sales-coaching assistant over a synthetic SPR (Sales
Process Record) dataset. Every output traces back to a real record or a
human-approved principle — *trust beats cleverness*. These docs cover the data,
the engines, and the surfaces.

## Surfaces & runtime

| Doc | What it covers |
|---|---|
| [`workspace.md`](workspace.md) | **The unified Senpai Workspace** — one conversational surface combining deterministic skills (`/review`, `/account`, `/research`), immutable grounded *artifacts*, and normal tool-calling chat. Shared conversation memory, in-place pick flow, Experience panel, manager parity. Supersedes the standalone Assistant + Review Coach pages. |
| [`accounts.md`](accounts.md) | **Account Intelligence** — the deterministic account engine (8-dimension account health, relationship-trajectory patterns, expansion opportunities, the roll-up), how the brief is fetched with grounding, the streamed senior account read, and the Accounts front end. |
| [`resolution_and_routing.md`](resolution_and_routing.md) | **Resolution, grounding & the reasoning router** — the customer-resolution cascade (alias index, word-boundary matching, ambiguity-as-state, fuzzy + LLM-ranked smart-resolve), the high/medium/low grounding trust model, and the FAST-vs-REASONING router (`no_think` prefill mechanism + the deterministic rule set). |
| [`llm_bridge.md`](llm_bridge.md) | **The FastAPI/LLM bridge** — SSE streaming protocol, the three streaming endpoints, conversation memory, deterministic routing (chat vs research vs follow-up), the resolution trust model, the tool-calling loop, and the `llama.cpp` serving setup. |

## Engines & data

| Doc | What it covers |
|---|---|
| [`coaching.md`](coaching.md) | The coaching system — Review Coach lenses, manager coaching workspace, rep profiles, rep progress, coaching threads, similar cases. |
| [`retrieval.md`](retrieval.md) | Retrieval over the knowledge base. |
| [`knowledge_extraction.md`](knowledge_extraction.md) | Extracting human-approved principles / playbooks from source material. |
| [`ingestion_integration_prompt.md`](ingestion_integration_prompt.md) | Ingestion / integration prompt for the knowledge pipeline. |
| [`synthetic_dataset.md`](synthetic_dataset.md) | The synthetic SPR dataset and its deterministic generation. |
| [`week5_phase2_week1_progress.md`](week5_phase2_week1_progress.md) | Phase 2 week-1 progress log. |
| [`phase25_session_log.md`](phase25_session_log.md) | **Phase 2.5 session log** — real Google Calendar tool (two-step confirm), dynamic junior-home stats, deal-dropdown grounding, the bug fixes (reasoning leak, slash picker, customer-id resolution, fastembed cache), the latency investigation (~395s→256s), and the two offline evals with measured results: **Atlas intent router** (built, evaluated, *not* shipped) and **model decomposition** (smaller synthesis model benchmark, round 2 pending). |

## The architecture in one paragraph

The Python **engines** (`senpai/coach`, `senpai/health`, `senpai/data/store`)
compute the deterministic record — health bands, coaching sections, source IDs —
over the synthetic SPR data. The **FastAPI bridge** (`senpai/api/server.py`)
serves that record as JSON and streams an LLM **senior read** over it via SSE,
while enforcing the resolution trust model (only high-confidence matches ground).
The **Next.js front end** (`web/`) renders deterministic artifacts that fill in
with streamed narration, all threaded through one shared conversation memory in
the **Workspace**.
