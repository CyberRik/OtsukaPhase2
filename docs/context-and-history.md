# Managing Context and History in Chat

Maintaining conversational memory is a multi-layered problem. We not only have to remember what was said, but we must also ensure that **background tools** (like a slide deck generator running on a parallel thread) have access to that exact same conversational context so they don't hallucinate facts.

Here is how history and context are maintained across the application.

---

## 1. The Standard Chat Loop (`convo` Object)
In `senpai/llm/client.py`, the conversation history is passed into `stream_chat_turn` as a mutable list of dictionaries (the standard OpenAI `messages` format). 
- As the model executes tool calls (e.g., retrieving a CRM record or searching the web), the tool requests and their actual results are appended **in-place** to the `convo` object.
- Because the results stay in the message history, the LLM naturally remembers the facts it gathered from previous turns and previous loops without needing to re-fetch them.

## 2. Router Memory (Stateful Affirmations)
Sometimes the user triggers a multi-turn operation (e.g., File Organization). The `WorkspaceOrganizeCapability` will first output a "Preview" and ask the user to confirm. 
- If the user simply replies "yes" or "go ahead", the **Intent Router** (`senpai/planner/selection.py`) needs to know *what* they are saying yes to.
- It uses `_recent_assistant_texts(history, limit=3)` to look backwards in the chat history. If it spots the `【整理プレビュー` marker in the recent history, it automatically routes the "yes" intent back into the LLMPlanner to execute the pending reorganization.
- Looking back multiple turns provides **fault tolerance**: if the user asks a side question in between, or if the Chat LLM briefly hallucinates an intermediate answer, the system still remembers the pending preview.

## 3. Tool Grounding (`ContextVars`)
A common failure mode in LLM agents is that a user says:
> *"Can you generate a proposal for that company we just talked about?"*

The standard Chat LLM knows what company it is, but the `generate_pptx` tool runs in isolation and doesn't have the chat history, so it generates a generic, hallucinated deck.

**How we solve this:**
1. Right before the Execution Engine dispatches parallel tools, `client.py` calls `set_conversation(convo)` (`senpai/tools/conversation.py`).
2. This drops a snapshot of the live conversation into a **`contextvars.ContextVar`**.
3. When the Execution Engine spawns new `threading.Thread` workers to run tools in parallel, it uses `contextvars.copy_context()` to ensure every worker thread safely inherits the conversation context.
4. The `ConversationCapability` reads this context, extracts the previously discussed companies/facts, and injects them into the new document's grounding bundle.

By using `ContextVar` instead of global variables, we guarantee that if 5 different users are talking to the server concurrently, their tools will never cross-contaminate each other's chat histories.

### 3a. Selecting *which* history to inject (relevance, not just recency)
`_conversation_grounding` (`senpai/tools/impl.py`) does not simply take the last N messages. Recency alone silently drops the entity in focus once a few unrelated turns intervene (a side question, extra tool calls) — which reintroduces the exact ungrounded-deck bug this grounding was built to prevent.

Instead it ranks by **relevance to the current request**:
- The most recent `_CONVO_RECENT_FLOOR` (3) snippets are always kept — the immediate context (the current request and the tool result that just landed).
- The remaining budget up to `_CONVO_MAX_SNIPPETS` (8) goes to the **older** snippets that best match the request, scored by token overlap with the prompt.
- Scoring is **script-agnostic** (`_relevance_tokens`): Latin/number words plus **CJK character bigrams**, so "村田印刷" shares the keys 村田/田印/印刷 across query and snippet. This deliberately avoids depending on the optional `janome` analyzer, whose whitespace fallback cannot segment Japanese.
- With no query signal at all, it degrades gracefully to pure recency (the original behavior).

### 3c. SessionFocus — the resolved entity (`senpai/tools/focus.py`)
Text grounding tells the doc author *what was said*; `SessionFocus` tells it *which record is in play*. It is **derived from the published conversation**, not a mutated object — the server is stateless per request and a per-turn `ContextVar` set on a worker thread doesn't survive to the next turn, so a live-mutated focus set when a CRM lookup resolved a customer would be gone by the next turn's document tool.

It is keyed off the **unambiguous IDs that real tool results emitted** (`D001` deal, `C13` customer), newest-first. An ID in a tool result means a tool *genuinely resolved* that entity, so focus is authoritative. It deliberately does **not** re-run fuzzy name matching — that is exactly what produced the wrong-company (松田 for a 村田 request) deck.

`_gather_grounding` now reads CRM in trust order: explicit customer arg → `SessionFocus` (deal in focus grounds on that specific deal) → fuzzy prompt match only as a last resort when the workspace didn't already pin the entity. This replaced the fragile `cust is None and not ws` guard and makes "that company we discussed" a lookup, not a re-inference.

### 3b. Boundary-aware truncation (`_truncate_on_boundary`)
Both the conversation grounding (4000-char budget) and each parallel tool result fed back to the model (`client.py`, 1500-char cap) are trimmed on a **natural boundary** — snippet break → paragraph → line → sentence → word — rather than a blind `text[:limit]`. A mid-string cut can drop the second half of a company name or a quote figure (`¥204,000`), handing the model half a fact; boundary trimming keeps facts intact and marks the elision with `…`.

---

## 4. Cross-chat memory (`senpai/orchestration/memory.py`)
Everything in §§1–3 is **same-chat** context: it lives only as long as the `convo` object. Cross-chat memory answers the other question — *"what do we already know about this deal from earlier sessions?"* — and it deliberately does **not** persist transcripts.

### 4a. What we persist: Observations, not history
The unit of cross-chat memory is the **`Observation`** (`senpai/orchestration/reason.py`) — a judgment the Reasoner already reached (`{claim, kind, materiality, citations, confidence}`), not a turn of dialogue. Persisting judgments instead of transcripts is the token-cheap form of memory: a later chat rehydrates a handful of compact, cited conclusions rather than whole histories (which is also what keeps the admin token dashboard's curve flat). Raw phrasing/chit-chat — 90% of a transcript — is never stored.

### 4b. The cross-chat spine: `EntityRef` + `as_of`
An observation is only cross-chat-useful if it is addressable by **what it is about** and **when it was reached**. So `Observation` carries:
- **`subject: EntityRef`** — `{type, id, display}` for a deal/account/contact/product, resolved to a **real id** (the same discipline as [SessionFocus](#3c-sessionfocus--the-resolved-entity-senpaitoolsfocuspy): ids from tool results, never fuzzy names). `subject.key` (e.g. `deal:D001`) is the stable lookup handle a store indexes on. An unanchored observation is not stored — there is nothing to key on.
- **`as_of`** — ISO-8601 UTC, stamped on persist if unset. This is the temporal spine: an account timeline is just *observations for subject X ordered by `as_of`*.

Retrieval keys off the entity already resolved for the turn — `SessionFocus.deal_id → store.by_subject(...)` — so pulling prior context is a structured lookup, not a semantic search, for the common in-focus case.

### 4c. The storage **seam** (`ObservationStore`) and its JSONL stub
`memory.py` defines the **interface**, not the storage:
```python
class ObservationStore(Protocol):
    def put(self, obs: Observation) -> None: ...
    def by_subject(self, subject: EntityRef, *, limit: int = 20) -> list[Observation]: ...
```
`JsonlObservationStore` is a working **stub** behind that seam: append-one-line-per-observation, `by_subject` scans + filters by `subject.key` newest-first. It is unindexed and intentionally minimal — **no dedup, no supersession** (those belong in the real backend, and adding them to a flat file would only be rewritten). It is thread-safe (the engine fans tools across worker threads) and tolerant of partial/malformed lines (a crash mid-write must not poison the store).

The point of the seam: it gives real cross-chat memory **today** — an observation written in chat A about `D001` is read back in chat B after a restart (`test_persists_across_store_instances`) — while the persistence layer's database becomes *just another `ObservationStore` implementation*. Callers hold the Protocol, so swapping the JSONL stub for the DB changes nothing upstream. `default_store()` is the lazy process-wide instance at `config.OBSERVATIONS_PATH` (gitignored, demo-only).

### 4d. Write-side: filling memory as a byproduct of reasoning
Observations are produced in exactly one place — the Reasoner's interpret pass (`LLMReasoner.interpret`, §on the Observation layer). So that is where they are persisted, at **zero extra model cost**: `LLMReasoner` takes an injected `on_observations` hook and calls it with the observations Compose already extracted. `reason.py` stays free of any tools/memory import — the hook is dependency-injected — so the orchestration layer never depends on `senpai.tools`.

A route wires the hook to `memory.remember_observations`, which:
- derives the turn's anchor from [SessionFocus](#3c-sessionfocus--the-resolved-entity-senpaitoolsfocuspy) via `subject_from_focus` (deal → account → None), so the same id discipline that grounds documents also keys memory;
- anchors each unanchored observation to that subject and `put`s it (an observation that already carries its own subject keeps it);
- **skips entirely when no entity is in focus** — an unanchored judgment has nothing to be recalled by, so it is not filed under nothing.

Persistence can never break a turn: the hook is wrapped so a store fault is swallowed after synthesis has already streamed.

> **Not yet wired (read-side).** This PR ships the anchor + seam + stub + the write hook. Still to come: routing `LLMReasoner` into the live workflows with `on_observations=remember_observations` (the M1 wiring), then injecting `by_subject` results into grounding (router-gated, token-capped, with an injected/dropped log for the dashboard).

> **Design note.** `ReasonerView` (`EvidenceBundle.to_reasoner_view`) stays a *derived, disposable* projection — it is never the persisted object. The durable objects are Evidence, Observations, and Artifacts, anchored by `subject`/`as_of`. Long-term, the same `ReasonerView` shape should be producible from **both** a live bundle and a store query over `(subject, time)`, so memory plugs in without changing the reasoning architecture.
