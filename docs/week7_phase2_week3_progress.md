# Senpai — Progress Report

### Internship Week 7 · Phase 2, Week 3 · June 26 – July 3, 2026

**Team:** AI Department (intern team) · **Audience:** Manager / mentors / Givery team
**Project:** Senpai — Sales Knowledge & Onboarding Copilot for Otsuka Shokai

> Covers work merged after the Week 2 report (`ae9945b`, "Merge PR #5") through
> `3b45cd8` (July 3). **43 feature commits · 45 new backend modules · 180 files ·
> +23,326 / −1,833 lines · 13 new test suites.**

---

## 0. Executive Summary

Week 2 turned the prototype into a credible product. **This week we turned the
product into a platform.** Every ad-hoc "gather-then-answer" code path was
rebuilt on a single reusable **orchestration spine**, and on top of that spine
we shipped four genuinely new capabilities — an LLM planner, a local-filesystem
agent, global segment sensemaking, and a live Graph-RAG visualization — plus the
operational plumbing (auth, admin portal, persistent chat history, token
accounting) that a real deployment needs.

Six headline directions this week:

1. **A unified Orchestration Engine (M0→M6).** One spine — *Planner → Execution
   Engine → Evidence Bundle → Reasoner → Artifact* — now powers Research, the
   multi-agent Crew, Account intelligence, and the chat tool-loop. Migrations
   were **parity-proven** (byte-for-byte identical evidence bundles) so the
   frontend couldn't tell anything changed, while gains — parallelism, partial-
   failure resilience, runtime DAG expansion — came for free.

2. **The LLMPlanner (goal → capability graph → artifact).** Document generation
   is no longer a monolithic tool. A user goal becomes an explicit capability
   graph the engine runs. Plain *"make a proposal for Murata Printing"* just
   works — no slash command — and it's correct with the model **off**, better
   with it on. IDs are always resolved deterministically, never by the model.

3. **A Local Workspace Agent.** Senpai stepped outside the seed database for the
   first time: it can now **search, read, synthesize into, and organize** the
   user's real local files — sandboxed, read-safe, with two-turn preview confirm
   on any destructive move.

4. **Segment Intelligence (GraphRAG).** A new global-sensemaking retrieval layer
   answers the *manager's* aggregate questions ("why do we lose manufacturing
   server deals?") — deterministic numbers, LLM prose that is machine-verified
   against those numbers, and it can never surface an invented figure.

5. **Admin Portal + live Graph-RAG visualization.** Org management, system
   observability, token accounting, and a real-time force-graph that *walks* a
   Graph-RAG traversal and scores it head-to-head against traditional vector
   retrieval — a compelling stakeholder demo.

6. **Product hardening.** Auth (signup/login), persistent chat history with a
   history drawer, a hybrid dual-model client with automatic failover and token
   tracking, unified Junior & Manager **Command Centers**, and a hardened tool-
   calling loop that provably can't spiral.

### Principles held (unchanged from Weeks 1–2)

| Principle | How it was upheld this week |
|---|---|
| **Deterministic first** | Every new subsystem computes its numbers in pure Python. Segment stats, ID resolution, capability planning fallbacks, and the reasoner's citation firewall are all deterministic. |
| **The model never invents an ID or a number** | The LLMPlanner picks *capabilities*, never IDs. Segment narratives are rejected if they contain any number not in the computed stats. The reasoner drops any observation whose citations don't trace to evidence. |
| **Correct without the model, better with it** | Planner, Segment Intelligence, and the workspace organizer all ship a deterministic fallback and run GPU-free when the served model is down. |
| **Grounded or silent** | Cross-chat memory persists only *cited* observations anchored to a real entity id; unanchored judgments are never filed. |
| **Zero-regression migration** | Every engine migration was gated by a parity suite proving identical output before the old path was retired. |

---

## 1. The Orchestration Engine — the flagship (`senpai/orchestration/`)

The core insight: four different routes (Research, Crew, Account, Chat) each had
their own hand-rolled copy of "gather from several sources in parallel, then run
one LLM over the result." We unified them into one spine so that **new
capabilities become additive** — write one class, register it — instead of
another rewrite.

```
plan ──► ExecutionEngine ──► EvidenceBundle ──► [Reducer] ──► Reasoner ──► [Approval Gate] ──► artifact
       (capabilities, DAG)   (immutable, cited)
```

**Design commitments** (`docs/orchestration-architecture.md`):

- **Planner emits a DAG, not a flat list** — tasks declare `depends_on`; the
  engine computes readiness continuously. Crucially the **DAG expands at
  runtime** (`ctx.expand`): a `find_documents` task returning N files appends N
  `extract` tasks, because the real breadth of a query is unknowable at plan
  time.
- **Capabilities own one domain and never reason, orchestrate, or call each
  other.** They do deterministic work and return a structured `Evidence`
  fragment. Their only window outward is `ExecContext` (deps, emit, expand,
  cancel, deadline).
- **The Evidence Bundle is immutable and append-only.** Each task writes exactly
  one fragment keyed by its id — no locks, order-independent. Two sources
  disagreeing is a *signal to the reasoner*, not something the engine resolves;
  provenance is always preserved.
- **One event vocabulary** describes DAG lifecycle only (`run.started`,
  `plan.expanded`, `task.started/progress/evidence/completed`, …). Adding a
  Browser or Email capability needs zero new event types. A single
  `<ExecutionTimeline>` front-end component renders both the multi-lane Crew and
  the single-stream Research from the same stream, just grouped differently.
- **Partial failure degrades, never crashes** — a capability that raises becomes
  an error fragment; the run still completes.

### Migration milestones shipped this week (M0–M6)

| Milestone | What shipped | Proof |
|---|---|---|
| **M0** | The engine itself (`capability.py`, `evidence.py`, `engine.py`, `events.py`, `scheduler.py`, `reason.py`, `reducer.py`) — GPU-free, no network, unit-tested in isolation. | Self-tested |
| **M1** | **Research** migrated onto the engine. Resolution, source emission, ambiguity, web-fallback, reasoner all unchanged. | `test_research_parity.py` — 84 cases assert `orch.to_dict() == legacy.to_dict()` |
| **M2** | **Crew + team fan-out** migrated. Researcher/Coach/Strategist UX preserved, but each agent's tool-gather now runs **in parallel** on the engine (a latency win) with grounding reassembled in fixed order. | `test_crew_parity.py` — 63 cases + full event-timeline test |
| **M3** | **Account gather** + a consolidation pass migrated. | `test_account_parity.py` — 123 cases (60 accounts × ja/en) |
| **M4** | **Chat tool-loop on the engine** via the new **AdaptiveScheduler**. The model just emits consecutive tool calls; the scheduler transparently batches independent `READ` ops into one parallel stage and makes `WRITE` ops act as barriers. The model stays unaware of the orchestration. | — |
| **M5** | **Workspace capability** — the first capability to reach *outside* the seed DB, and the first production use of runtime DAG expansion (`ctx.expand`). | `test_workspace.py` — 7 cases |
| **M6** | **LLMPlanner** — goal → capability graph → artifact, proven on document generation (see §2). | `test_planner.py` — 8 cases |

**Parity strategy (why we trust the migration):** because the LLM answer is
non-deterministic we never diff generated text — we prove the **evidence bundle
fed to the reasoner is identical** to the legacy path, and the artifact is
constructed identically. Old builders were kept as a *parity oracle*, not
deleted, and only retired once parity was confirmed. Full suite after each
milestone: **219 → 282 → 405 passing, zero new regressions.**

---

## 2. LLMPlanner — document generation as a capability graph (`senpai/planner/`)

`docs/llm-planner.md` is the full teaching doc. The problem: `generate_pptx`
secretly did two very different jobs at once — **gather grounding** (conversation,
files, CRM, web) and **author the document**. That hidden `if`-sequence doesn't
generalize to "prepare tomorrow's meeting."

The planner makes the gather **explicit**. A user goal becomes a capability graph:

```
goal ─► LLMPlanner.select()  ─► one simple_complete picks {capabilities, doc_kind}  (strict JSON)
     ─► document_plan()      ─► fixed 2-level DAG: gather tasks (parallel) → one documents task
     ─► ExecutionEngine.run  ─► EvidenceBundle
     ─► documents capability  ─► assembles grounding most-specific-first → author → render → register
     ─► artifact {doc_id, filename, download_url}
```

Key properties:

- **The model picks capabilities; deterministic code resolves identity.** A
  hallucinated capability list can only *widen or narrow* the gather — it can
  never point the deck at the wrong deal, because IDs are resolved in
  `selection.py` from the store (`D###`, else customer name → primary open deal).
- **Correct without the model.** With `SENPAI_USE_LLM` off, `heuristic_selection`
  picks capabilities deterministically; the proposal path is fully GPU-free.
- **Wired into normal chat — no `/plan` prefix.** `_is_document_goal` routes a
  *create-verb + document-noun* message through the planner, emitting the same
  `plan | context | tool | document | answer` events the chat UI already renders.
  Plain *"make a proposal for 村田印刷"* just works. `POST /api/plan` remains as
  an explicit programmatic surface. (稟議書 stays on its dedicated template in the
  ReAct loop — intentionally excluded.)
- **Minimal by design:** not autonomous, not recursive, not re-planning — one
  goal → one static plan → one artifact. Meeting-prep and account-intelligence
  are the *same spine* plus a real Reasoner pass, next.

### 2.1 Post-ship hardening: correctness, observability, and richer decks

Dogfooding the planner against real customer names surfaced a class of bugs the
parity suites couldn't catch (they diff evidence bundles, not judgment calls) —
fixed the same day, all covered by direct re-verification against the live
backend, not just unit tests:

- **Ambiguous customers now surface a picker instead of guessing.** "matsuda" →
  four different 松田 companies; the planner path had no ambiguity guard (chat
  and `/crew` already did), so it silently ground on nothing and let the model
  free-associate. Now short-circuits to the same candidate picker every other
  surface uses.
- **Deal-openness no longer dictates document *style*.** A customer whose deals
  are all Confirmed/Lost (not "open") was silently downgraded from a sales
  proposal to a generic analytical deck — and separately, the LLM's own
  capability-selector could override a *correctly* resolved deal back to
  `pptx`. Both fixed: a resolved deal always grounds `generate_proposal`,
  regardless of rank; style (`playbook.deck_style_guide`) is now decided by
  whether a customer resolved, not by deal stage.
- **Deeper CRM grounding.** The customer-scoped path pulled a 5-field deal
  summary only; the deal's actual activity/daily-report log (competitor
  mentions, budget blockers, decision-maker status) was never fetched, so the
  model *guessed* a plausible-sounding cause instead of citing the real one.
  `CRMCapability` now includes it.
- **The outline is no longer thrown away.** Both the deterministic
  `generate_proposal` spec and the free-authored deck already computed their
  slide list before rendering, but the capability discarded it after use — the
  rep only ever saw a filename. It now rides in `Evidence.data` and surfaces
  two ways: inline in the answer text ("構成: 1. … 2. …") and as a numbered
  list in the tool card, both before the download link.
- **Live tool-call streaming.** The planner ran the whole plan synchronously
  and only synthesized tool-call cards from the final result — every card
  landed in one burst *after* the file was already done, reading as if the
  answer appeared before any tool ran. Now streams real `task.completed`
  events off a background thread as they happen (same queue/thread pattern
  `/crew` already used), one card at a time, live.
- **Tool names now localize.** The planner baked Japanese labels directly into
  the event instead of a stable id the frontend could translate — so the
  language toggle did nothing for planner-generated cards, and the grounding
  badge (which keys off the same lookup) always read "generic output," even
  for a fully CRM-grounded proposal. Both now resolve through the same
  `TOOL_LABEL` dictionary every other tool already uses.
- **Multi-deal proposals.** `generate_proposal` was single-deal by
  construction — "a proposal covering all of C33's deals" silently dropped
  every deal but the largest. It now merges pain points, matched products,
  comparables, and financials (summed) across every deal a rep names, with an
  explicit "対象案件一覧" slide listing what's included.
- **Richer proposal deck.** `generate_proposal` gained an executive-summary
  slide, a real IT-environment/assessment slide (SPR `environment` record, not
  invented), a **table** layout for the solution slide (product/code/price)
  and a **chart** layout for the ROI slide (standard vs. proposed spend), plus
  a standard implementation-schedule table — same deterministic-numbers
  guarantee, just fewer walls of bullet text.

---

## 3. Local Workspace Agent (`senpai/workspace/` + `senpai/planner/`)

Senpai can now act on the user's **real local files** (`docs/workspace-expansion.md`).
Three operations, all sandboxed to `WORKSPACE_ROOT`:

- **Search & read** — `find` relevance-ranks documents and **fans out one
  `extract` task per hit** (runtime DAG expansion). Extraction handles PDF, DOCX,
  PPTX, XLSX, TXT/MD; char-capped and never raises (a corrupt file yields empty
  text + a note). Citations are `file://<rel>`.
- **Synthesize a note** — `workspace_write` authors a markdown note from the
  gathered grounding and writes it under `notes/` via a confirm-gated
  `edit_workspace_document`.
- **Organize** — `workspace_organize` tidies loose root-level files into topic
  folders (`quotes/`, `proposals/`, `meeting-notes/`, …) using an LLM JSON
  classifier with a deterministic keyword fallback.

**Safety is the headline:**
- Every path (symlinks included) must resolve inside `WORKSPACE_ROOT` via
  `safe_path`; `../../` escapes throw `SandboxError` (unit-tested).
- Strictly **read-only search** — there is no delete op by design.
- **Two-turn preview confirm** for organize: the first pass defaults to
  `op="plan"` and only lists the moves it *would* make; it executes only when the
  goal carries an explicit apply cue ("apply" / "実行") *or* is an affirmation
  ("go ahead" / "はい") confirming a pending preview. `move_within` never
  overwrites and never leaves the sandbox, so even a mis-fire can't lose data.

---

## 4. Segment Intelligence — GraphRAG community summarization (`senpai/graph/`)

Senpai's three retrieval layers (hybrid semantic, keyword-RAG, graph multi-hop)
are all **local** — they fetch specific rows. None can answer the *global*
question a manager asks: 「製造業のサーバー案件、なぜ負ける？」. Stuffing ~100 dead
deals into the context is over-budget and low-signal on our ~11 tok/s model.

We adapted **Microsoft's GraphRAG** pattern (`docs/segment-intelligence.md`,
`docs/senpai_graph_architecture.md`):

- **We skip GraphRAG's expensive step 1** (LLM entity/relationship extraction —
  ~2,337 calls, hallucinated edges) because we *already* have a clean typed graph
  built directly from structured SPR data (`graph/build.py`, a
  `networkx.MultiDiGraph` with denormalized deal nodes for millisecond queries).
- **We skip Leiden clustering** — communities are **deterministic facets**
  (`product_category × industry`), which are more interpretable than a Leiden
  blob on our small hub-heavy graph.
- So our pipeline is just GraphRAG's steps 3 + 4, where the value is.

**The core rule: deterministic numbers, LLM prose, *verified* prose.**
1. Every statistic (win rate, deal counts, top failure signals) is computed in
   Python via the existing deal-health engine — zero LLM.
2. The LLM writes only 2–3 sentences of Japanese narrative, **offline at build
   time**, over *only* the stats JSON.
3. A **grounding gate** (`ungrounded_numbers`) rejects the prose if it contains
   any number not in the whitelist; on rejection (or model-down) it falls back to
   a deterministic templated sentence.

Reports are committed as `communities.json` (like the vector index). At runtime
the `segment_intelligence` tool loads them, `select()` returns bounded context
(broad questions → ~7 category rollups, not 37 leaves), and the chat loop's
existing synthesis round does the "reduce" for free — no nested LLM call.
`test_communities.py` (7 tests) includes a **hand-count parity** test and the
**grounding invariant** (`ungrounded_numbers(narrative) == []`), a
machine-checkable version of "no invented numbers."

---

## 5. Intelligent tool-calling & loop prevention (`senpai/llm/client.py`)

A hardened ReAct loop that provably can't spiral (`docs/tool-calling-intelligence.md`):

- **`finish` sentinel** — round 0 forces `tool_choice="required"` so the model
  *must* gather before answering (no throwaway reply); once evidence exists it
  relaxes to `"auto"`. When done, the model calls `finish`, which we intercept to
  break the loop instantly — saving a latency + context "dummy" turn.
- **Anti-spiraling cap** — a tool used across more than `_TOOL_ROUND_CAP` (2)
  *unproductive* rounds gets short-circuited with a nudge to answer with what's
  collected. It counts unproductive rounds, not total, so distinct-entity
  lookups never trip it.
- **Terminal-action hard stop** — once a deliverable tool (`generate_*`,
  `schedule_meeting`, `create_quote`, `send_email`) commits, the loop terminates
  immediately, preventing duplicate documents.
- **Exact deduplication** — `_canon_args` normalizes JSON args; a repeat call in
  the same turn is served from cache.
- **Boundary-aware truncation** — tool results are trimmed on natural boundaries
  (paragraph → line → sentence → word), never mid-string, so a company name or a
  ¥ figure is never cut in half.

**Scoped multi-entity expander** (`_multi_entity_gather_calls`, `docs` §8):
"compare D133, D012, D168" used to take one round *per deal* (~75s) and the
anti-spiral cap would block the 3rd, making the model hallucinate "couldn't
retrieve D168." Now, when round 0 names ≥2 distinct **known** ids, we synthesize
the whole gather bundle ourselves (each deal → health + records) and the
AdaptiveScheduler runs all 6 calls in **one** parallel round (~28s), all three
deals fully gathered. (Measured. The doc also records why the model *won't*
self-batch under the full operational prompt — a nice piece of empirical
analysis: batching only reappears if you strip the grounding-first prompt, which
we won't.)

---

## 6. Context & history + cross-chat memory (`senpai/tools/`, `senpai/orchestration/memory.py`)

`docs/context-and-history.md`. The failure mode: a user discusses a company, then
asks "make a deck" — a background thread that can't see the conversation
generates a generic hallucinated deck.

- **Thread-safe conversation grounding** — before the engine dispatches parallel
  tools, `set_conversation(convo)` drops a snapshot into a `contextvars.ContextVar`;
  worker threads inherit it via `copy_context()`, so 5 concurrent users never
  cross-contaminate.
- **Relevance, not just recency** — `_conversation_grounding` keeps the 3 most
  recent snippets plus the best older matches scored by token overlap, using
  **script-agnostic CJK bigrams** so "村田印刷" matches on 村田/田印/印刷.
- **`SessionFocus`** — the resolved entity, keyed off unambiguous IDs from real
  tool results (`D001`, `C13`), never fuzzy names — which is exactly what
  produced the wrong-company (松田 vs 村田) deck before.
- **Cross-chat memory (seam shipped)** — persists **`Observation`s, not
  transcripts**: cited judgments anchored to a real `EntityRef` + `as_of`
  timestamp, filled as a zero-cost byproduct of the Reasoner's interpret pass. A
  JSONL stub sits behind an `ObservationStore` Protocol. Write-side is wired;
  read-side injection is the next PR.

---

## 7. Two-pass Reasoner with a citation firewall (`senpai/orchestration/reason.py`)

The single place where reasoning happens. It splits synthesis into two passes:

1. **Interpret** — the evidence view becomes a small set of typed, **cited**
   `Observation`s (judgments, not restatements), temp 0, structured JSON. **Any
   observation whose citations don't trace back to evidence is dropped** — an
   uncited claim is a hallucination and never reaches the artifact.
2. **Compose** — the artifact is authored from the ranked observations
   (deterministic materiality ranking: high/medium/low), with raw evidence still
   available for exact figures.

If Interpret yields nothing usable (or the model is down), Compose falls back to
single-shot synthesis — no regression. Ships with a deterministic `EchoReasoner`
(GPU-free, for tests) and the `LLMReasoner`.

---

## 8. Hybrid dual-model client: failover + token accounting (`senpai/llm/`)

- **Hybrid model-decomposition** — the final synthesis round is routed by a
  `ReasoningRouter`: FAST (no-think) synthesis goes to a smaller **8B Q4**
  fallback model; THINK-grade mentorship narrative stays on the **primary 27B**.
  Quality where it matters, speed where it doesn't.
- **Automatic failover** — if the primary endpoint fails mid tool-loop, the
  client transparently retries on the fallback server (`⚠️ Primary server failed…
  Trying fallback`) instead of crashing the turn.
- **Token accounting** (`senpai/llm/usage.py`) — every completion records one
  JSONL row (server-reported `usage` when available, else a clearly-labelled
  local `estimated=True` figure — the UI never presents a guess as measured).
  Best-effort recording that can never break inference; surfaced on the admin
  Usage page.

---

## 9. Admin Portal + live Graph-RAG visualization (`web/app/admin/**`, `senpai/api/server.py`)

A first-class operations surface (`docs/admin_visualization.md`,
`docs/commit-3761dfc.md`). New `/api/admin/*` endpoints: overview, reps table,
org chart, activity feed, accounts, pipeline health, system status, usage
tracking, and graph visualization. Includes **rep reassignment** via a
`reports_to` overlay upsert.

The showcase piece — migrated from a fragile standalone WebSocket demo into the
real app as **SSE**:
- **Network graph** — the full NetworkX graph rendered with
  `react-force-graph-2d` (dynamically imported, SSR-disabled), colored by node
  kind, labels drawn only for high-degree/highlighted nodes.
- **Community map** — a custom heat-map of category × industry leaves, tile size
  ∝ deal count, color ∝ win rate.
- **Live traversal** — `POST /api/admin/graph-rag/run` streams `node_visited` /
  `edge_traversed` events that visually *walk* the Graph-RAG path, dimming the
  rest of the graph.
- **Versus scorecard** — runs the same query through Graph-RAG **and** a
  traditional vector search, then emits a `comparison` event scoring latency,
  token counts, and chunk sizes head-to-head. **This is the money demo for
  stakeholders.**

---

## 10. Product plumbing

- **Auth — signup & login** (`senpai/api/auth.py`, `web/app/signup`) — signup
  maps accounts onto seed reps (junior adopts a rep; manager adopts a coach
  scoped by coaching threads). `test_auth.py`.
- **Persistent chat history** (`senpai/data/chat_store.py`,
  `web/components/workspace/history-drawer.tsx`) — SQLite-backed durable
  transcripts; list/retrieve/upsert/rename/delete; a History Drawer with live
  search.
- **Junior Command Center** — six isolated pages collapsed into one split-pane
  home where context and the AI Copilot live side-by-side; real drag-and-drop
  ingestion with a first-run 3-step guide.
- **Manager Command Center** — the `command-center.tsx` shell made role-generic;
  a team-triage left pane (at-risk deals + reps to coach) that grounds the
  Copilot on click — "what's the risk?" with no slash command. Killed a 3-way
  route duplication in the dashboard.
- **Real-time TTS**, a separate Copilot dashboard, and hierarchical multi-agent
  tool logging in the Crew UI.
- **Central config module** (`senpai/config.py`) — environment-based tunables for
  model, inference, and data paths, so nothing is hardcoded.
- **ClientBadge & Profile UI integration** — added `ClientBadge` component, integrated it into Login and Landing pages, and made the profile optional in the ContextPane.
- **Senpai backend bridge** — implemented a typed API client bridging the FastAPI backend and the frontend orchestration engine.
- **Legacy auth cleanup** — removed the deprecated legacy authentication module (`senpai/apps/manager_dashboard.py`).

---

## 11. Testing & quality

**13 new test suites this week** (30 total), all GPU-free:

| Suite | Guards |
|---|---|
| `test_research_parity` / `test_crew_parity` / `test_account_parity` | Engine migrations produce byte-identical evidence bundles (270 cases combined) |
| `test_planner` | Goal → capability graph → registered downloadable artifact |
| `test_workspace` | Sandbox escapes rejected; find→extract fan-out; capped |
| `test_communities` | Hand-count parity + grounding invariant |
| `test_tool_loop_guard` / `test_multi_entity_expander` | Loop can't spiral; compare-pattern fan-out |
| `test_focus` / `test_memory` / `test_memory_write` / `test_reason_observations` | Entity resolution + cited-observation persistence |
| `test_auth` | Signup → seed-rep identity mapping |

Every engine migration was **zero-regression** — the parity suites confirmed
identical behavior before any legacy path was retired.

- **Synthesis benchmarking framework** (`scripts/bench_synth_prompt.py`, `senpai/llm/synth_style.py`) — introduced a framework to benchmark synthesis prompts and an optimization module to evaluate and improve output style.

---

## 12. Suggested demo flow (for the presentation)

1. **Plain chat → document** — type *"make a proposal for Murata Printing"*; no
   slash command; watch the `plan` event show the chosen capability graph, then
   the download chip appear. (§2)
2. **Local workspace** — *"find the latest Yamato quote in my files"* → *"save
   the talking points as a note"* → *"organize my files"* → preview → *"go
   ahead"*. Shows the sandboxed agent + two-turn confirm. (§3)
3. **Manager segment question** — 「製造業のサーバー案件、なぜ負ける？」 → grounded
   aggregate answer with cited deal IDs. (§4)
4. **Graph-RAG Versus page** — run a query, watch the traversal walk the graph,
   then show the scorecard beating traditional retrieval. (§9)
5. **Compare deals** — *"compare D133, D012, D168"* → one parallel round instead
   of three sequential (28s vs 75s). (§5)

---

## 13. What's next

- **LLMPlanner for meeting-prep / account-intelligence** — the same spine plus a
  real Reasoner pass over the bundle and a Reducer to compact overflowing local
  files ("prepare me tomorrow's Endo Kogyo meeting").
- **Wire cross-chat memory read-side** — inject `by_subject` observations into
  grounding (router-gated, token-capped).
- **Deferred simplification** — converge the four bespoke reasoners onto
  `reason.py`, unify the SSE dialects, and (product decision) collapse the
  multi-agent flow into one Planner → Engine → Reasoner path.
- **Approval Gate + ConnectionProvider** — generalize today's `confirm=` into the
  reserved `OperationKind=WRITE` gate; wire per-user auth for external Email /
  Calendar capabilities.
