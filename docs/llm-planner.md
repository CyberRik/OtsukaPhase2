# LLMPlanner — goal → capability graph → artifact (teaching doc)

A walkthrough of the planner we added: **what problem it solves, the design it commits
to, how it's built, how it plugs into normal chat, and how to extend it.** Written so a
new teammate can read this once and confidently touch the code.

Companion docs: `docs/orchestration-architecture.md` (§M6 is the summary of this) and
`docs/segment-intelligence.md` (the pattern the capabilities reuse).

---

## 1. The problem, in one picture

Document generation used to be a single tool the model called — `generate_pptx` /
`generate_proposal`. That tool secretly did **two very different jobs at once**:

1. **Gather grounding** — look at the conversation, the local files, the CRM, the web.
2. **Author the document** — turn that grounding into slides.

Everything about "which sources should ground this deck?" was hidden *inside* the tool,
as a fixed sequence of `if` branches. That's fine for one document type, but it does not
generalize: the moment you want "prepare me for tomorrow's meeting" (CRM + notes +
segment reports + local proposals + web) the hidden-sequence approach collapses, and you
cannot see, test, or reorder the steps.

**The LLMPlanner makes the gather explicit.** A user goal becomes a **capability
graph**: nodes are capabilities (Conversation, Workspace, CRM, Knowledge, Web,
Documents), edges are dependencies. The planner decides *which capabilities are needed*;
the existing Execution Engine runs them; the resulting EvidenceBundle feeds the terminal
Documents capability, which authors the artifact.

```
User Goal
    ↓
LLMPlanner          decide WHICH capabilities are needed (one decision)
    ↓
ExecutionPlan       a fixed DAG: gather tasks → one documents task
    ↓
Execution Engine    reused — runs the DAG in parallel
    ↓
Evidence Bundle     reused — one immutable fragment per capability
    ↓
Reasoner            (trivial for docs: the artifact IS the file)
    ↓
Artifact            a registered, downloadable .pptx / .docx
```

---

## 2. The idea, and what it is *not*

The planner is **capability-driven, not tool-driven**, and **deliberately minimal**.

- It is **not** an autonomous agent. It does not loop, does not react to results, does
  not re-plan. It makes exactly **one** decision — the capability set — and emits a
  **static** plan.
- It is **not** recursive. There is no planner-inside-a-planner, no sub-goals.
- It does **not** reason over results. Reasoning is the Reasoner's job (and for a
  document, the artifact is the file, so there's nothing to synthesize yet).
- It does **not** rewrite business logic. Every capability is a thin adapter over code
  that already exists (`query_spr`, `workspace_evidence`, `search_knowledge`,
  `web_search`, `author`/`proposal`/`render`/`registry`).

This is milestone 1 on purpose: **prove the planner can orchestrate capabilities for
document generation.** Meeting-prep and account-intelligence are the same spine plus a
real Reasoner pass — a later milestone, not this one.

---

## 3. The core design principle

> **The model picks capabilities. Deterministic code resolves identity. The engine
> executes. Grounding flows through the bundle — never re-gathered.**

Three commitments fall out of that:

1. **The LLM never handles IDs, ordering, or execution.** It returns a capability list
   and a document kind — nothing else. The customer/deal a document grounds in is
   resolved from the store (`selection.py`), so a hallucinated capability list can only
   *widen or narrow the gather*; it can never point the deck at the wrong deal. This is
   the same "never invent an ID / a number" rule the rest of Senpai follows.

2. **Correct without a model, better with one.** With `SENPAI_USE_LLM` off (or the model
   down), `heuristic_selection` picks the capabilities deterministically and the proposal
   path renders with zero LLM calls. The model is an *enhancement* to selection, never a
   dependency of it.

3. **The Documents capability consumes the bundle; it does not re-gather.** The grounding
   that used to be a hidden side-effect inside `generate_pptx` is now the explicit gather
   half of the graph. The terminal capability reads `ctx.deps` and assembles the
   grounding block from what the selected capabilities actually put in the bundle.

---

## 4. Architecture / data flow

```
goal ─► LLMPlanner.select() ─────────────────►  Selection
        │  (1) heuristic_selection: deterministic default + resolve deal/customer IDs
        │  (2) if model up: one simple_complete picks {capabilities, doc_kind} (strict JSON)
        │      → ground_selection re-grounds IDs, enforces invariants; junk → heuristic
        ▼
   document_plan(selection)  ─────────────────►  ExecutionPlan (fixed 2-level DAG)
        │   Level 0 (parallel):  conversation / workspace / crm / knowledge / web
        │   Level 1 (terminal):  documents ── depends_on every gather task
        ▼
   ExecutionEngine.run(plan)  ────────────────►  EvidenceBundle
        │   gather capabilities emit {"text","label"} grounding (READ/SEARCH, degrade to empty)
        │   documents capability (WRITE): reads ctx.deps → assembles grounding →
        │       author/proposal → render → registry.register
        ▼
   run_document_goal reads the `documents` fragment  ─►  artifact {doc_id, filename, download_url}
```

Notice the symmetry with `docs/segment-intelligence.md`: **capabilities return grounded
retrieval; the reduce happens elsewhere.** There, the reduce is the chat loop's synthesis
round. Here, the "reduce" is the Documents capability authoring the file. No nested LLM
call sits inside a gather capability.

---

## 5. The files, and why each exists

`senpai/planner/` — the whole surface is small on purpose.

### `selection.py` — the decision + deterministic grounding
- **`Selection`** — the immutable plan the planner emits: `capabilities`, `doc_kind`,
  `deal_id`, `customer_id`, `target`, `lang`, `reason`.
- **`_resolve_entity(goal, deal_hint)`** — the ID-grounding choke point. A `deal_hint`
  (the deal the rep picked in the selector) is authoritative; then an explicit `D###` in
  the goal; then a customer name → its **primary open deal** (largest amount). Returns
  `None`/`None` when the entity isn't in the CRM (a workspace-only company) — then a free
  deck grounds on workspace/conversation instead.
- **`heuristic_selection(goal, deal_hint)`** — the deterministic default and the
  always-available fallback. Always gathers `conversation`; adds `workspace`
  (self-gated on a real file match), `crm` when an entity resolved, `knowledge` for
  proposals, `web` for external/factual topics with no internal entity.
- **`ground_selection(goal, caps, doc_kind, …)`** — takes an LLM-chosen capability set +
  doc kind and re-grounds it: conversation is always kept; a `proposal` with no
  resolvable deal degrades to a free `pptx`; `crm` is dropped if nothing resolved.
- **`_pick_doc_kind`** — proposal (deal or 提案/proposal cue) / docx (文書/report cue) /
  pptx (default). **`稟議` (ringisho) is intentionally excluded** — it has its own
  dedicated template (`generate_ringisho`) and stays in the ReAct loop.

### `capabilities.py` — gather adapters + three terminal producers
Gather (all emit a uniform `{"text","label"}`, degrade to empty, never raise):
- **`ConversationCapability`** → `impl._conversation_grounding` over the published convo.
- **`WorkspaceCapability`** → `impl._workspace_grounding` (relevance-gated find→extract).
- **`CRMCapability`** → `impl.query_spr` for the resolved deal/customer.
- **`KnowledgeCapability`** → `impl.search_knowledge` (attributed playbook snippets).
- **`WebCapability`** → `impl.web_search`.

Terminals (exactly one runs, chosen by `doc_kind`; all read `ctx.deps`, none re-gather):
- **`DocumentsCapability`** (`op` = proposal/pptx/docx) — assembles the grounding block
  **most-specific-first** (conversation → workspace → crm → knowledge → web), then
  authors + renders + **registers** a downloadable file, reusing
  `author`/`proposal`/`render`/`registry`. Emits `{text, document:{doc_id,…},
  grounded_on:[…]}`.
- **`WorkspaceWriteCapability`** (`op="note"`) — WRITES a short markdown note **into the
  workspace** (a persisted file the rep keeps, not a download), authored from the same
  gathered grounding. Reuses the existing sandbox-checked, confirm-gated
  `impl.edit_workspace_document`; it never opens a path itself.
- **`WorkspaceOrganizeCapability`** (`op="plan"|"apply"`) — TIDIES the workspace: buckets
  loose root-level documents into topic folders (quotes / proposals / meeting-notes /
  reports / contracts / other) by a deterministic filename classifier. `plan` previews
  (read-only, the default — moving real files is destructive); `apply` performs the
  moves via the sandbox's no-overwrite `move_within`. Files already in a subfolder are
  left alone. This is a self-contained terminal — it has **no gather** graph.

### `plan.py` — the fixed DAG
- **`document_plan(selection)`** — gather tasks at level 0 (parallel, no deps), one
  `documents` task depending on all of them. The `depends_on` edges *are* the ordering;
  no sequencing logic lives in the engine or the capabilities. The documents task carries
  `TaskPolicy(retries=0)` — a WRITE deliverable must never be auto-repeated.

### `llm_planner.py` — the one LLM call
- **`LLMPlanner.plan(goal, …)` / `.select(goal, …)`** — starts from
  `heuristic_selection`; if the model is up, one `simple_complete` (strict JSON,
  validated against the known capability names) refines the capability set + doc kind,
  and any failure falls straight back to the heuristic. The model chooses *what to
  gather*, never IDs, ordering, or execution. Implements the `Planner` protocol seam that
  has existed since M0.

### `run.py` — end to end
- **`run_document_goal(goal, conversation=…, deal_id=…)`** — publishes the conversation
  (so the Conversation/Documents capabilities see it), plans, runs on the shared
  `ExecutionEngine`, and reads the terminal `documents` fragment as the artifact.
  `python -m senpai.planner.run "D001 の提案書"` runs it (proposal path is GPU-free).

---

## 6. How it plugs into normal chat (no `/plan` prefix)

The planner is **integrated into the ordinary chat surface** — a rep just types a normal
prompt. `senpai/api/server.py`'s `chat()` routes by intent:

```
/api/chat  ─►  research intent?          → research_stream        (source-grounded research)
           ─►  _is_document_goal(msg)?    → _plan_stream           (the LLMPlanner)   ← new
           ─►  otherwise                  → stream_chat_turn       (the ReAct tool loop)
```

- **`_is_planner_goal(message)`** (in `selection.py`, aliased into the server) is the
  router. It fires for three intents, all owned by the planner:
  - **document generation** — a *create* verb (make / generate / 作成 / 作って …) + a
    *document* noun (proposal / deck / pptx / docx / report / 提案書 / スライド …);
  - **note write** — save / jot / record / メモ / 保存 aimed at a file, a note, or `.md`/
    `.txt` ("save this as a note to murata_followup.md");
  - **organize** — organize / tidy / sort / 整理 / 片付け over files / documents / the
    workspace.
  Organize and note are checked first (their phrasing can also contain a document noun).
  It stays tight so ordinary tool asks — "draft an email", "make a quote", "tell me about
  X", "D168 のリスクを教えて" — stay in the ReAct loop. `稟議` is excluded.
- **Destructive ops are preview-first, with a two-turn confirm.** `organize` defaults to
  `op="plan"` (read-only — it lists the moves it *would* make); it performs moves only
  when the goal carries an explicit apply cue (apply / do it / 実行 / やって) **or** when
  it's an affirmation confirming a pending preview. That second case is the natural chat
  flow: "organize my files" → preview, then a bare "go ahead" / "yes" / "はい" → apply.
  It works because both the router *and* the selection layer look at the **last assistant
  message** (`_last_assistant_text`): if it carries the preview marker (`【整理プレビュー`)
  and the new message is an affirmation, the turn is an organize-apply — not a fresh goal.
  This is deliberate: without threading the preview context into *selection* (not just
  routing), a bare "go ahead" would be re-classified from scratch and the LLM could
  mis-pick `docx` and generate a stray document. `move_within` never overwrites and never
  leaves the sandbox root, so even a mis-fire can't lose data.
- **`_plan_stream(goal, convo, role, deal_id)`** is the shared SSE generator used by both
  the auto-routed chat turn and the dedicated `POST /api/plan`. It emits the **same event
  shapes the chat UI already renders** — `plan | context | tool | document | answer |
  done` — so the download chip and account-focus chip appear with no frontend change. An
  attached file rides along as conversation context; a selector-picked `deal_id` is
  authoritative.

The ReAct loop's `generate_*` tools are **untouched** — they remain for mid-conversation
generation the model decides to do. The planner is an *additive* front door for
top-level document goals, not a replacement. `POST /api/plan` also remains as an explicit
surface (and for programmatic callers).

---

## 7. How to run it

```bash
export SENPAI_TODAY=2026-06-16                 # pin scoring's "today" to the seed anchor

# End-to-end from the CLI (proposal path is GPU-free — no model needed):
C:/Python313/python.exe -m senpai.planner.run "make a proposal for Murata Printing 村田印刷"

# Tests (no model needed):
C:/Python313/python.exe -m pytest tests/test_planner.py -q

# Live, through the dedicated surface (model up for the pptx/docx authoring path):
curl -sN -X POST http://127.0.0.1:8000/api/plan -H "Content-Type: application/json" \
  --data '{"message":"make a deck on the best gaming laptops under 1000000 yen","history":[]}'

# Live, through NORMAL chat (auto-routed — no /plan prefix):
curl -sN -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" \
  --data '{"message":"make a proposal for Murata Printing","role":"junior","history":[...]}'
```

Sample chat event stream (auto-routed document goal):

```
{"type":"start","surface":"planner"}
{"type":"plan","doc_kind":"proposal","capabilities":["conversation","workspace","knowledge"],
 "target":"有限会社村田印刷","deal_id":"D001","tasks":[…4 tasks, documents depends on 3…]}
{"type":"context","status":"active","customer":"有限会社村田印刷","deal_id":"D001"}
{"type":"tool","name":"会話の文脈","result":"根拠を収集しました。"}
{"type":"tool","name":"ローカル文書","result":"根拠を収集しました。"}
{"type":"tool","name":"資料生成","result":"提案書(PPTX)を生成しました: proposal_D001_…pptx",
 "document":{"doc_id":"…","download_url":"/api/documents/…"}}
{"type":"answer","text":"提案書(PPTX)を生成しました: proposal_D001_…pptx"}
```

Note that in this run the **model chose** `["conversation","workspace","knowledge"]` and
*dropped CRM* — it judged the Murata quote in the local file plus the session context
sufficient. That's the planner making a real capability-selection decision, distinct from
the deterministic heuristic (which would have included `crm`).

---

## 8. Why it's built this way — design notes

- **Reuse over rewrite.** The engine, EvidenceBundle, events, `author`/`proposal`/
  `render`/`registry`, and the doc tools' own `_conversation_grounding` /
  `_workspace_grounding` are all existing utilities. The planner is mostly *composition*
  — the new code is the selection logic, six thin adapters, one DAG builder, and the
  routing.
- **The graph is the API.** Because the plan is expressed in capabilities with explicit
  `depends_on` edges, "what grounds this document" is now inspectable (the `plan` event),
  testable (assert the DAG), and reorderable — none of which was true when the gather was
  a hidden `if`-sequence inside a tool.
- **Grounding promoted, not duplicated.** The Documents capability reads the bundle
  rather than re-gathering, so there is exactly one gather per source per goal — no
  double web-search, no double file read.
- **Same event shapes = free UI.** By emitting `plan | tool | document | answer`, the
  planner rides the existing chat renderer (tool cards + download chip + focus chip) with
  zero frontend work. The `plan` event is extra metadata the current handler safely
  ignores; a future UI can render the capability graph from it.
- **Reduce is deferred, not faked.** For a document the artifact is the file, so `run.py`
  returns the fragment directly. The `reason.py` Reasoner seam is where meeting-prep /
  account-intelligence will synthesize prose over the bundle — the honest next step.

---

## 9. Known limits & future work

- **Compound goals.** "Make a proposal for D168 **and** tell me the risks" routes to the
  planner and produces the proposal; the "risks" clause is dropped. The router is
  intentionally tight, but it does not split compound requests. Acceptable for milestone
  1; a future planner could emit a plan that includes a Reasoner answer alongside the
  artifact.
- **One terminal per goal.** The plan has a single terminal (documents / note write /
  organize). "Make a deck **and** a one-pager" is not yet expressible.
- **Organize is a deterministic filename classifier.** It buckets by keywords in the
  file *name* (見積/quote → quotes, 提案/proposal → proposals, …), not by reading content.
  It's predictable and GPU-free; an LLM-refined taxonomy (read a bit of each file, infer
  the folder) is a natural upgrade. It only reorganizes files sitting at the workspace
  *root* — already-filed documents in subfolders are left alone.
- **Ringisho stays in the ReAct loop.** `generate_ringisho` has a bespoke template the
  planner doesn't model, so 稟議 requests are excluded from routing. Folding it in is a
  small follow-up (add a `ringisho` doc kind + capability op).
- **No frontend `/plan` command — by design.** The planner is reached through normal
  prompts (§6); there is deliberately no slash-command. A future UI could render the
  `plan` event's capability graph as a small "sources chosen" panel.
- **The next milestone is the expansion, not a rewrite.** Meeting-prep and
  account-intelligence add (a) more selectable gather capabilities (e.g. Segment
  Intelligence — see `docs/segment-intelligence.md` §8 — and Activities) and (b) a real
  Reasoner pass over the bundle, with the Reducer compacting when local files overflow
  the context. The spine in this doc does not change.

---

## 10. TL;DR

We turned document generation from a single tool that secretly did gather-then-author
into an explicit **capability graph**. The **LLMPlanner** makes one decision — *which
capabilities ground this document* — and emits a static `ExecutionPlan`; the existing
engine runs it; the EvidenceBundle feeds a terminal Documents capability that authors the
file. IDs are resolved deterministically (never by the model), it's correct with the
model off and smarter with it on, and it's wired into **normal chat** — a plain "make a
proposal for …" prompt just works, no `/plan` prefix. It is minimal by design: not
autonomous, not recursive, one goal → one plan → one artifact. Meeting-prep and
account-intelligence are the same spine plus a Reasoner, next.
