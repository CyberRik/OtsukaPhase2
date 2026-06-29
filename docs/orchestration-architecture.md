# Orchestration architecture

The reusable spine that turns Senpai's per-route gather/synthesis logic into one
layer: a **planner** produces a DAG of deterministic **capabilities**, an
**execution engine** runs them in parallel and collects their structured output
into an immutable **evidence bundle**, and a single **reasoner** synthesizes the
artifact. New capabilities (Filesystem, Email, Calendar, Browser, Office) become
*additive* — write one class, register it — instead of another rewrite.

> Status: **M0 + M1 + M2 + M3 shipped.** M0 = the engine (`senpai/orchestration/`).
> M1 = Research. M2 = crew + team gather. M3 = account gather (`senpai/account/`),
> plus a consolidation pass (dead code removed, shaping de-duplicated). All
> retrieval-heavy workflows now share the spine, all parity-proven and live. What
> remains is the deferred simplification phase. See "Migration" below.

---

## The pipeline

```
plan ──► ExecutionEngine ──► EvidenceBundle ──► [Reducer] ──► [Reasoner] ──► [Approval Gate] ──► artifact
          (capabilities)                          stub          seam            future
```

Two stages beyond the naive line exist because of the long-horizon target query
(*"prepare me for tomorrow's Endo Kogyo meeting — gather every proposal, quote,
note, PPTX, PDF, calendar event, email, playbook, then summarize and draft a
follow-up"*):

- **Reducer** — gathering "every document" overflows any single reasoner context.
  A map-reduce compaction step sits between bundle and reasoner. M0 ships a
  pass-through; a real `MapReduceReducer` lands when a capability can produce
  bundle-overflowing volume.
- **Approval Gate** — "draft a follow-up" is *effectful*. WRITE tasks pause the DAG
  for human approval. Today's two-step `confirm=` in `generate_*` is a hand-rolled
  instance; the gate generalizes it. Deferred until the first WRITE capability.

---

## Why this shape

Three of Senpai's five orchestration surfaces are *already* plan→gather→bundle→reason,
just hardcoded and inconsistent:

| Target concept | Already exists as | Location |
|---|---|---|
| EvidenceBundle | `ResearchBundle` (has provenance) | `api/server.py` |
| Capability executors | tool fns + `store` + `score_deal` | `tools/impl.py`, `data/store.py` |
| Parallel engine | `_worker` + `queue.Queue` + threads | `agent/crew.py` |
| Single reasoner | 4 copies of "one LLM over context" | research / crew / account / team |
| Target resolution | `resolve_crew_target`, `resolve_customer_detailed` | `crew.py`, `store.py` |

The one genuinely LLM-*planned* surface is `/api/chat`'s `stream_chat_turn` (the
model picks tools dynamically). **Scope: unify the four deterministic surfaces
(research, crew, account, team); leave the chat tool-loop alone.** It may later
share the same capabilities, but its dynamic planning stays.

---

## Design decisions

### Planner — a dynamic DAG
Not a flat list (can't express "web only if CRM misses" or "reason after all"),
not fixed execution levels (a barrier between levels stalls independent work). A
**DAG**: tasks declare `depends_on`; the engine computes readiness continuously.
Crucially the DAG **expands at runtime** — `Filesystem.find_documents` returns N
refs → the engine appends N `Office.extract` tasks. The breadth of a real prep
query is unknowable at plan time.

The planner stays *non-reasoning*: seed plans are deterministic; runtime expansion
is data-driven (not an LLM). A `Planner` Protocol seam lets a future `LLMPlanner`
choose capabilities for open-ended requests without touching the engine. **M0/M1
build plans as plain functions** — no Planner object yet.

### Task — 4 core fields, policy defaulted
```python
Task(id, capability, op="", inputs={}, depends_on=frozenset(),
     policy=DEFAULT_POLICY, group="default", summary="")
```
- `inputs` are literals; a task reads upstream outputs from `ctx.deps` — **no Ref
  DSL** (added later only if ergonomics demand).
- `TaskPolicy(timeout_s, retries, on_failure)` — one small struct, capability-level
  defaults. WRITE safety = the plan sets `retries=0`; no `OperationKind` enum yet.
- A Task carries **no result** — outcomes live in the bundle, keyed by `task.id`.
  Plan and result stay separate, which is what keeps both immutable.

### Capability — one domain, stable interface
```python
class Capability(Protocol):
    name: str
    def run(self, op, inputs, ctx) -> Evidence: ...
```
A capability owns a domain (CRM has `lookup_deal`/`list_proposals`; `run` dispatches
on `op`). It does deterministic work, returns structured `Evidence`, and **never
reasons, orchestrates, or calls another capability**. Its only window outward is
`ExecContext`:

```python
ExecContext(task_id, inputs, deps, emit, expand, cancel, deadline)
#   deps     upstream evidence by task id
#   emit     report a sub-step  -> task.progress event
#   expand   request new tasks  (runtime fan-out)
#   cancel   cooperative cancellation token
```
New cross-cutting concerns (auth/connections, tracing) are added as `ExecContext`
fields later — no capability signature changes.

### EvidenceBundle — immutable, append-only, no reconciliation
Each task writes exactly one `Evidence` fragment keyed by its id; fragments never
overwrite each other → no locks, order-independent. Two sources disagreeing is
**signal for the reasoner**, not something the engine resolves — provenance is
always preserved.

```python
Evidence(status, data, citations, confidence, provenance,
         task_id, capability, op, group, timing)   # last 5 stamped by the engine
```
- `data` is structured JSON, never markdown. `citations` are human handles
  ("SPR D003", "Playbook PB12", "file://…#slide3") the artifact can quote.
- `provenance` (machine locus, for audit/Retrieval-Explorer) is kept distinct from
  `citations` (renderable). `to_reasoner_view()` is the canonical, error-dropped,
  deterministically-ordered view the Reducer/Reasoner consume.

### Execution engine — one threaded scheduler loop
`ExecutionEngine.run(plan, emit) -> EvidenceBundle`. ThreadPoolExecutor, not
asyncio (the OpenAI client and store are blocking; threads parallelize them with no
stack rewrite; `crew.py` already proves the model). The loop:

1. absorb any tasks a running capability asked to add (`ctx.expand`)
2. submit every PENDING task whose dependencies are all terminal
3. wait for the next task; record evidence, emit events
4. if a `fail_run` task failed → cancel and drain
   until nothing is pending and nothing is running.

Supports: dependency-aware scheduling, parallelism, retries (READ-safe ops),
cooperative cancellation, **partial failure** (default `on_failure="skip"` — one
bad capability degrades, never crashes the run), runtime expansion. A capability
raising is caught and turned into an error fragment.

---

## Event model — one vocabulary

The engine is the single source. Events describe the **DAG lifecycle**, never a
domain — adding Browser/Email needs zero new event types. Every event carries
`type, run_id, seq` (monotonic), `ts`.

```
run.started {groups, planned_count}      plan.expanded {added_count, total_count}
task.started {task_id, capability, op, group, summary}
task.progress {task_id, message}         task.evidence {task_id, status, confidence, citations}
task.completed {task_id, duration, status}
task.retrying / task.failed              group.completed {group}
run.completed {completed, failed} / run.cancelled
# reserved (route/Reducer/Reasoner, not engine): reduce.* reason.* artifact.created
#                                                 approval.required auth.required
```

`group` + `summary` are the only layout drivers: a multi-lane `/crew` and a
single-stream `/research` are the **same event stream**, different grouping → the
front-end collapses to one `<ExecutionTimeline>` (Cursor / Deep-Research style).
During migration, thin per-route adapters translate these to the legacy SSE names
so the existing UI keeps working byte-for-byte.

---

## The Endo Kogyo walkthrough

1. **Resolve** "Endo Kogyo" → `customer_id` (existing resolver; ambiguity → picker).
2. **Seed plan** (deterministic `meeting_prep` template): parallel READ tasks —
   `CRM.list_deals/list_proposals/list_quotes`, `Activities.meeting_notes`,
   `Filesystem.find_documents`, `Calendar.find_events`, `Email.recent`,
   `Knowledge.relevant_playbooks`.
3. **Runtime expansion**: `find_documents` → N refs → `ctx.expand(Office.extract×N)`;
   `Email.recent` → threads → `Email.fetch_thread×M`. `plan.expanded` fires.
4. **Parallel gather** under per-capability concurrency caps + auth. `Email` token
   expired → `auth.required`; that branch degrades, the rest proceeds.
5. **EvidenceBundle** accumulates ~30 fragments with citations + confidence.
6. **Reducer** (30 docs overflow the reasoner) → per-document/group map summaries.
7. **Reasoner** (single) → prep summary + follow-up plan, citing sources.
8. **Approval Gate**: "draft follow-up" is WRITE → `approval.required` + preview →
   on approve, `Email.draft` / `Office.export_pptx` → `artifact.created`.

### Weaknesses this surfaces (and the answers)

| Weakness | Mitigation |
|---|---|
| Context overflow on "every document" | **Reducer** map-reduce before synthesis |
| Per-user auth/secrets for external caps | `ConnectionProvider` field on `ExecContext`; `auth.required` event |
| Cost / rate limits (Browser, APIs) | per-capability concurrency caps + `priority` + timeouts + cancellation |
| Effectful safety/ordering (send, book) | `OperationKind=WRITE` + **Approval Gate**; no auto-retry/cache |
| Repeated work across sessions | content-addressed `cache` key in `TaskPolicy` |
| Open-ended intent phrasing | `Planner` seam → future `LLMPlanner`, same `ExecutionPlan` |
| Non-reproducibility of web/email/browser | provenance + timestamps make it *auditable*, not reproducible |

The first four mitigations are *seams reserved in M0* (event constants,
`ExecContext`/`TaskPolicy` shape), not yet implemented — so adding them is not a
rewrite.

---

## M0 — what shipped

`senpai/orchestration/`, GPU-free, no network, not wired to routes:

| File | Role |
|---|---|
| `capability.py` | `Task`, `TaskPolicy`, `ExecutionPlan` (+cycle check), `Capability`, `ExecContext`, `CapabilityRegistry` |
| `evidence.py` | `Evidence` (`ok/empty/error`), `EvidenceBundle` (views, `to_reasoner_view`), `Timing` |
| `engine.py` | `ExecutionEngine` — the one scheduler loop |
| `events.py` | the unified event vocabulary (constants + shapes) |
| `reason.py` | `Reasoner` Protocol + `EchoReasoner` (no-LLM) + `LLMReasoner` (lazy) |
| `reducer.py` | `Reducer` Protocol + `PassthroughReducer` |
| `planner.py` | `Planner` Protocol seam |
| `__main__.py` | self-test |

**Self-test** (`python -m senpai.orchestration` → `RESULT: PASS`) proves: parallelism
(7 tasks 0.5s wall vs ~1.4s serial), dependency ordering, runtime fan-out, retries,
partial-failure degradation, ordered timeline, citations, error-dropping view.

### Simplifications taken (deferred, with a seam)
Planner classes, `Ref` input-binding DSL, `OperationKind` enum + Approval Gate, full
Reducer/Reasoner impls, plan-level reasoner/reducer specs, `priority`/`cache`/per-op
`defaults`, `ConnectionProvider`/`auth.required` — all dropped from M0, each kept as
a Protocol stub or a reserved field/constant so it is additive.

---

## Migration (zero-regression first)

- **M0** ✅ scaffolding, isolated, unit-tested.
- **M1** ✅ Research over the engine — parity-proven, live (details below).
- **M2** ✅ Crew + team gather over the engine — multi-agent UX preserved (below).
- **M3** ✅ Consolidation + account gather over the engine — parity-proven (below).
- **Simplification phase** (deferred, post-migration) — converge the three reasoners
  onto `reason.py`, unify the SSE dialects onto `events.py`, then (a product
  decision) collapse the multi-agent flow into one Planner → Engine → Reasoner.
  `/api/chat`'s dynamic tool-loop stays until the `LLMPlanner` seam is built.

Capabilities call `store`/`scoring` directly (structured), not the string tools in
`impl.py` — those stay for the chat loop. `llm/client.py` is untouched; the Reasoner
wraps `stream_complete`.

---

## M1 — Research migrated (parity-proven)

The Research gather now runs on the engine; resolution, source emission, ambiguity,
web-fallback, and the reasoner are unchanged. **The frontend cannot tell.**

`senpai/research/`:

| File | Role |
|---|---|
| `shaping.py` | byte-for-byte replicas of the server's `_deal_summary` (split into `deal_facts` + `health_read`), `_activity_summary`, `_public_customer`, `_products_for_deals` |
| `capabilities.py` | `CRM`, `Activities`, `SimilarDeals`, `Health`, `Environment`, `Web` — thin wrappers over `store` / `score_deal` / `find_similar_deals` / `web_search_typed` |
| `plan.py` | `research_plan(mode=customer\|deal)` + `web_plan()` |
| `gather.py` | runs the engine, re-merges facts+health, rebuilds provenance per mode → the exact legacy field set |

**The DAG (proves dependency handling):** `crm`, `activities`, `similar_deals`,
`environment` run in parallel; **`health` depends on `crm` + `similar_deals`** (it
scores every deal id they surfaced). The gather re-merges
`{**deal_facts, "health": …}` into the identical legacy `_deal_summary` shape.

**Wiring:** `_build_research_bundle` / `_build_deal_context_bundle` get `*_orch`
twins that the live `/research` (and the chat research route) call; the legacy
builders are kept as the **parity oracle**, not deleted (per "remove only after
parity is confirmed").

**Parity strategy:** the LLM answer is non-deterministic, so we don't diff text — we
prove the *evidence bundle fed to the reasoner is identical*
(`orch.to_dict() == legacy.to_dict()`), which makes artifact quality identical by
construction. `tests/test_research_parity.py` (84 cases): 40 customers × valid-
customer bundle, 40 deal-context bundles, citations present, not-found shell,
web-fallback pass-through, and **partial-failure degradation** (a capability raising
→ that source becomes empty/`not_found`, the run still completes — where the legacy
inline code would have crashed). Full suite: **219 passed, 0 regressions** (the one
remaining `test_research.py` failure is pre-existing and unrelated — verified
identical with M1 changes stashed).

**One deviation:** the not-found **web fallback stays on the direct `web_search_typed`
seam**, not routed through the engine. It is a single external call (not gather
orchestration) and existing tests patch that symbol; routing it through a 1-task plan
added no value and moved a test seam. `WebCapability` is still built and exercised by
the golden test via `web_search_via_engine`.

---

## M2 — Crew gather migrated (multi-agent UX preserved)

`/crew` (and the `/team` fan-out) keep their exact UX — Researcher + Coach run in
parallel, then the Strategist synthesizes a Strategy Brief — but each agent's data
gathering now runs on the engine. Prompts, artifacts, streaming events, and
provenance are unchanged.

**Why not the M1 capabilities directly?** The crew prompts were written against the
*string* outputs of the deterministic tools (`query_spr`, `find_similar_deals`,
`search_notes`, …); M1's capabilities emit *structured* evidence for the research
summarizer. Feeding the crew M1's structured bundle would change its grounding and
therefore its artifact. So M2 shares the **engine and the same underlying tool
layer**, via one tiny capability rather than the M1 capability classes:

`senpai/agent/`:

| File | Role |
|---|---|
| `capabilities.py` | `ToolCapability` — runs any existing tool through `impl.dispatch(op, inputs)`. One wrapper over the shared tool layer; **zero retrieval logic duplicated** (no CRM/Activities/Health/Environment/SimilarDeals/Web reimplemented). |
| `plan.py` | `researcher_plan` (4 tools) / `coach_plan` (1) / `rep_analyst_plan` (2) — same tools, args, order, and human summaries as before. |
| `gather.py` | `run_agent_gather(plan, agent_id, emit)` — runs the plan, translates each `task.started` into the legacy `agent_tool` event (same name/summary/order), returns the tool strings for the agent to assemble its grounding. |

`crew.py`'s `_run_researcher` / `_run_coach` / `_run_rep_analyst` lost their inline
tool calls and now call `run_agent_gather`; everything else (the parallel `_worker`
threads, the prompts, `_run_strategist`, the `crew`/`agent`/`final`/`done` events) is
untouched. Net effect: each agent's tools now run **in parallel** instead of
sequentially (a latency win), with the grounding reassembled in the prompt's fixed
order so the artifact is identical.

**Parity** (`tests/test_crew_parity.py`, 63 cases): per-deal researcher grounding ==
legacy tool strings (30 deals), coach grounding == legacy (30), rep-analyst gather ==
legacy, partial-failure degradation (a tool raising → empty slot, gather completes),
and an **end-to-end `run_crew` event-sequence test** (LLM stubbed) asserting the full
`crew → agents+agent_tool → strategist → final → done` timeline is preserved. Full
suite: **282 passed, 0 new regressions** (same single pre-existing `test_research.py`
failure, unrelated).

After M2, every retrieval-heavy workflow (research, crew, team) shares the engine.
The remaining per-agent reasoning (Researcher/Coach/Strategist prose) is intentionally
kept — collapsing it into a single Reasoner is the post-migration simplification, not
part of M2.

---

## M3 — Consolidation + account migrated

Three steps, recommended order, parity-first:

**1. Dead code removed.** `_legacy_research_stream` (server.py) — an unused duplicate
of the live `research_stream` and the only remaining caller of the legacy
`_build_research_bundle` — deleted. The legacy bundle builders stay (now used only by
the M1 parity oracle).

**2. Shaping de-duplicated.** `_deal_summary` / `_public_customer` / `_activity_summary`
/ `_products_for_deals` existed byte-identically in both `server.py` and
`research/shaping.py`. `research/shaping.py` is now canonical; the server functions
are thin aliases that delegate to it (preserving every call site and the implicit
`_today()` default). The M1/M2 parity suites (147 cases) confirm no behavioral change.

**3. Account gather on the engine** (`senpai/account/`):

| File | Role |
|---|---|
| `capabilities.py` | `AccountContextCapability` — wraps `build_account_context` as structured evidence (same call, same `(context_text, meta)`) |
| `plan.py` | `account_plan()` — a single gather task |
| `gather.py` | `gather_account_context()` — runs the plan on the engine; degrades to the package's own not-found shape on failure |

`account_commentary` now calls `gather_account_context` instead of
`build_account_context`. The commentary artifact is driven entirely by
`account_commentary_prompt(context_text)`, so identical `(context_text, meta)` ⇒
identical prompt ⇒ identical artifact. The route's events (`start` / `artifact_meta`
/ `context` / `strategy` / `delta` / `done`), the prompt, and the inline reasoner
stream are untouched.

The account context is one composite text+meta unit, so it is wrapped as a **single**
capability (like M1's web fallback). Decomposing it into the shared
CRM/Health/Environment capabilities — and converging the account prompt onto
structured evidence — belongs to the simplification phase, not M3.

**Parity** (`tests/test_account_parity.py`, 123 cases): 60 accounts × {ja, en} assert
`gather_account_context == build_account_context`, plus not-found parity and
degraded-failure resilience. Full suite: **405 passed, 0 new regressions** (same lone
pre-existing `test_research.py` failure).

---

## Migration complete — state of the spine

Every retrieval-heavy workflow now gathers through the engine:

| Workflow | Gather | Reasoner (still bespoke) | Events |
|---|---|---|---|
| research | engine (6 caps, DAG) | `_summarize_research_bundle` | source/answer |
| crew | engine (`ToolCapability`) | per-agent `simple_complete` + strategist | agent/agent_tool |
| team | engine (`ToolCapability`) | team-lead `simple_complete` | agent/agent_tool |
| account | engine (1 cap) | inline `stream_complete` | context/delta |
| `/api/chat` | LLM-planned tool loop (intentionally not migrated) | routed synthesis | tool/delta |

The deferred simplification phase is now the only remaining work: (1) converge the
four reasoners onto `reason.py`; (2) unify the three SSE dialects onto the
`events.py` vocabulary once the frontend can consume it; (3) the product decision on
collapsing the multi-agent flow; (4) build the `LLMPlanner` seam to fold in
`/api/chat`. None of these are required for correctness — they are consolidation.

---

## M4: Adaptive Execution (The Chat Loop Integration)

The `/api/chat` tool loop has now been integrated with the orchestration engine using a new **AdaptiveScheduler**. 

Instead of requiring the LLM to explicitly reason about parallelism (e.g. through a `parallel_map` tool), the runtime transparently identifies opportunities for parallel execution. The LLM simply emits consecutive tool calls in a single turn, and the scheduler determines execution strategy.

### 1. Capability Metadata and Policies
Every tool declares an execution `policy` (`READ` or `WRITE`) and a `namespace`:
- `READ` tools are side-effect free (e.g., `web_search`, `search_products`) and can be run concurrently.
- `WRITE` tools mutate state (e.g., `schedule_meeting`, `generate_pptx`) and must run sequentially.

### 2. The AdaptiveScheduler
When the LLM emits a set of independent tool calls:
1. The scheduler partitions the calls into batches (stages).
2. Consecutive `READ` operations are grouped into a single parallel stage.
3. `WRITE` operations act as barriers, forcing preceding stages to resolve and running sequentially themselves.
4. An `ExecutionPlan` is generated and passed to the existing `ExecutionEngine`.

This allows a prompt like *"Find the best laptops from MSI, ASUS, Lenovo, and Acer"* to execute 4 web searches simultaneously in the backend, radically reducing latency, while the LLM remains completely unaware of the orchestration mechanics.

### 3. Stability and UI
- **Context Length Safety**: When many parallel tools run, their concatenated output could overflow the context window (particularly for the fallback model). To guarantee stability, the engine actively truncates massive parallel payloads (e.g. to 1500 chars) before handing the evidence bundle back to the Reasoner.
- **Visualizing Parallelism**: In the frontend, tool events are tagged with a `batchId`. The `workspace` chat UI dynamically groups tools from the same batch and renders them using a hierarchical "ticks and squares" timeline, clearly exposing the parallel execution behavior to the user.
