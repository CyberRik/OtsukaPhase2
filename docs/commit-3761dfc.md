Persistent Chat History for the Senpai Workspace

Context

Today the copilot chat ("Senpai Workspace") has no persistence. The transcript
lives only in a module-level JS Map in web/lib/chat-store.ts (keyed
workspace:${role}:thread), which is wiped on every full page reload/tab close.
There is no way to list past conversations or resume one. The backend /api/chat
is stateless â it rebuilds context from the history the client re-sends each turn,
and keeps only in-memory focus caches keyed by conversation_id (lost on restart).

Goal: make conversations durable and cross-device, add a UI to list/open/rename/
delete past chats, and let a user resume any past chat exactly where it left off â
including the rich skill/artifact turns (review, account brief, research, crew cards).

Decisions (locked with the user)

- Storage: SQLite (stdlib sqlite3, single file), not flat JSON and not
localStorage. Chosen for its write/query shape (frequent writes, per-user
recency listing, unbounded growth, cheap single-row rename/delete) and to avoid
store.py's lru_cache-reload and O(N)-rewrite pitfalls. It stays completely
separate from store.py (chat writes must never call store.reload()).
- Full fidelity: the server stores an opaque, client-owned JSON blob (the
serialized transcript + associated cached narration/answer strings) plus a small
server-readable header for listing. The server never parses the blob.
- Both junior and manager workspaces; auto-save every conversation
(debounced, after each completed turn). Title derived from the first user message.
Rename + delete supported.
- Client-driven save (not server-side inside /api/chat). Rationale: /api/chat
only receives ChatMessage{role,content} (server.py:1326) and never sees the
WMsg[]/artifact objects, so it physically cannot produce a full-fidelity blob.
Keeping saving on the client leaves the core chat streaming path untouched.

---
Architecture overview

Workspace (client, owns WMsg[] + cache keys)
   â  autosave (debounced, on turn complete)     load / list / rename / delete
   â¼                                                     â²
web/lib/api.ts  âââº  FastAPI  senpai/api/server.py  âââº  senpai/data/chat_store.py  âââº  chat_history.db (SQLite, WAL)
   (contract: types.ts + api.ts + fixtures)         (new /api/chat/history/* routes)   (INGESTED_DIR, gitignored)

/api/chat (the SSE streaming endpoint) is not modified.

---
Backend

1. New persistence module â senpai/data/chat_store.py

Standalone; imports only stdlib sqlite3, json, threading, datetime, and
senpai.config. Never touches store.py or its lru_cache.

- DB path: add CHAT_DB_PATH = INGESTED_DIR / "chat_history.db" to
senpai/config.py alongside the other data paths (gitignored, same dir as
users.json).
- Schema (idempotent CREATE TABLE IF NOT EXISTS, run at import via init_db()):
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  employee_id     TEXT NOT NULL,
  role            TEXT NOT NULL,        -- 'junior' | 'manager'
  title           TEXT NOT NULL,
  created_at      TEXT NOT NULL,        -- ISO8601 UTC
  updated_at      TEXT NOT NULL,
  message_count   INTEGER NOT NULL,
  blob            TEXT NOT NULL         -- opaque client JSON (WMsg[] + cache)
);
CREATE INDEX IF NOT EXISTS ix_conv_owner
  ON conversations (employee_id, role, updated_at DESC);
- Concurrency/atomicity: PRAGMA journal_mode=WAL. Open a fresh short-lived
connection per call (cheap; sidesteps check_same_thread since FastAPI runs
sync endpoints in a worker threadpool) and guard writes with a module-level
threading.Lock. WAL permits concurrent readers + one writer. UPSERT via
INSERT ... ON CONFLICT(conversation_id) DO UPDATE SET ....
- Functions:
  - init_db() â create table/index + set WAL (idempotent).
  - list_conversations(employee_id, role) -> list[dict] â header rows only
(no blob), newest-first via the index.
  - get_conversation(conversation_id) -> dict | None â header + blob.
  - upsert_conversation(conversation_id, employee_id, role, title, blob, message_count)
â sets created_at on insert, always bumps updated_at.
  - rename_conversation(conversation_id, title) -> bool.
  - delete_conversation(conversation_id) -> bool.

2. New endpoints in senpai/api/server.py

Follow the existing endpoint style (Pydantic request models, thin handlers). Group
near the other /api/coach/* listable-thread endpoints. Identity is passed
explicitly as employee_id (query/body) â consistent with /api/coach/rep-profile/{employee_id}
etc.; no auth enforcement added (none exists today).

- GET  /api/chat/history?employee_id=&role= â list[ConversationHeader].
- GET  /api/chat/history/{conversation_id} â ConversationDetail (header + blob) orÂ 404.
- PUT  /api/chat/history/{conversation_id} â upsert; body SaveConversationRequest {employee_id, role, title, blob, message_count} â returns ConversationHeader.
- PATCH /api/chat/history/{conversation_id} â body {title} â rename.
- DELETE /api/chat/history/{conversation_id} â {ok: true}.

Pydantic models: ConversationHeader (conversation_id, role, title, created_at,
updated_at, message_count), ConversationDetail (header fields + blob: str),
SaveConversationRequest, RenameRequest.

---
Frontend

Contract-sync order (per docs/web-integration.md, verified by
scripts/check_contract.py): endpoint â web/lib/types.ts + web/lib/api.ts â
web/lib/fixtures.ts â UI.

3. Contract â web/lib/types.ts + web/lib/api.ts

- types.ts: ConversationHeader, ConversationDetail (mirror backend). Define the
blob envelope type StoredThread { version: 1; messages: WMsg[]; cache: Record<string,unknown>; nextId: number; focus?: WorkspaceFocus }
(kept in a shared spot the workspace can import). nextId preserves the idRef
counter so resumed turns don't collide.
- api.ts: add listConversations(employeeId, role), getConversation(id),
saveConversation(id, payload), renameConversation(id, title),
deleteConversation(id). Reuse the existing authGet/authPost-style helpers and
the { data, live } return convention so API-down degrades gracefully
(live:false).

4. Serialize / rehydrate helpers â extend web/lib/chat-store.ts

The transcript is spread across multiple cache keys, so add two small primitives:
- snapshotEntries(keys: string[]): Record<string,unknown> â read a set of keys.
- restoreEntries(entries: Record<string,unknown>): void â setCached each.
- Extend useCachedConversationId to also return set(id) (set ref + cache) so a
loaded conversation can adopt its stored id.

Build the blob in Workspace via a serializeThread(convId, role). All three
per-turn cache-key families must be snapshotted, or streamed text is lost on resume:
- messages: getCached('workspace:${role}:thread'); nextId: current idRef.current.
- cache: snapshotByPrefix([...]) covering:
  - ws:chat:${convId}: â assistant-turn text + :started flag (workspace.tsx:591-592)
  - ws:crew:${convId}: â crew-turn streamed contributions (crew-turn.tsx:30)
  - ws:art:${m.artifact.id}: â per skill turn's artifact id (art-<ts>-<rand>,
artifacts.ts:70), covering :narr|done|started|... (workspace.tsx:260-265,
read back by buildChatHistory at 710-711)
  - workspace:${role}:focus
Restoring the :started/:done flags is what prevents finished turns from
re-streaming when the conversation is reopened.
- focus: current useWorkspaceFocus value.

5. Auto-save hook (in workspace.tsx)

A debounced effect (~800ms) that fires when a turn completes:
useEffect(() => { if (busy) return; if (!hasRealTurn(messages)) return; schedule(save); }, [busy, messages]).
save() builds the blob via serializeThread, derives title from the first
role:"user" message (truncated), and calls api.saveConversation(thread.current, { employee_id, role, title, blob, message_count }). Guards: skip while busy
(mid-stream) and skip transcripts with no user+assistant pair. Failures are
swallowed (chat keeps working ephemerally). employee_id from useSession(); if
absent, skip persistence.

6. Load / resume (in workspace.tsx)

loadConversation(id):
1. const { data } = await api.getConversation(id); parse blob â StoredThread.
2. restoreCached(data.cache); setCached('workspace:${role}:thread', messages).
3. thread.set(id); idRef.current = data.nextId (restore the counter so nextId()
won't collide â idRef is otherwise set once at mount, workspace.tsx:829).
4. Restore focus; clear composer/dealId.

"New chat" = existing clearThread() (workspace.tsx:1094) â it already empties
the transcript and mints a fresh conversation_id. The new row is created lazily by
the first turn's autosave.

7. History UI â new web/components/workspace/history-drawer.tsx

A left slide-over drawer (not a permanent rail) triggered by a "History" button
placed beside the existing Clear/New control in the Workspace header. Chosen over an
inline rail because the junior home already has a left context-pane
(command-center.tsx) and the manager workspace renders Workspace bare â a drawer
works uniformly on both without layout conflicts.

- Mirror components/workspace/context-pane.tsx list styling: search box + .map
of clickable <Card> rows, active row highlighted (ring-2 ring-primary/40) when
id === thread.current.
- Each row: title, relative updated_at, inline rename (pencil) + delete (trash).
- Fetches api.listConversations(employeeId, role) on open (cheap; also refetch
after a save completes). Scoped by role so a junior blob never opens in the
manager workspace and vice-versa.
- Row click â loadConversation(id) (passed down from Workspace) + close drawer.
- Delete of the currently-open chat â call clearThread().
- API-down / empty â "No saved chats yet" or "History unavailable" (from live:false).

8. Fixtures â web/lib/fixtures.ts

Add an empty conversation list fallback returned with live:false when the API is
down, matching the existing offline pattern.

---
Edge cases

- Concurrent tabs, same conversation: last-write-wins via UPSERT (acceptable at
demo scale; updated_at reflects the latest write).
- Delete currently-open chat: reset to a fresh thread via clearThread().
- Role mismatch: list + load are role-scoped; a manager can't see/open junior chats.
- Empty/new reps: DB auto-creates; list is simply empty.
- Backend down: autosave silently no-ops, chat still works in-memory as today;
drawer shows "History unavailable".
- Very long transcripts: blob TEXT handles it at demo scale; no pagination.
- Migration/back-compat: chat_history.db is created on first use and gitignored
like users.json; no seed data, nothing to migrate.

---
Staged execution

1. Backend persistence: senpai/config.py (CHAT_DB_PATH) + senpai/data/chat_store.py (schema, WAL, CRUD).
2. Backend endpoints: /api/chat/history/* + Pydantic models in server.py. (/api/chat untouched.)
3. Contract: web/lib/types.ts, web/lib/api.ts, web/lib/fixtures.ts.
4. chat-store helpers: snapshotEntries/restoreEntries + useCachedConversationId.set.
5. Workspace wiring: serializeThread, autosave effect, loadConversation, History button.
6. UI: history-drawer.tsx (mirrors context-pane.tsx).

Verification

- Contract drift: python scripts/check_contract.py (in-process TestClient, no GPU) must pass.
- Backend unit (pytest): create â list â get â rename â delete round-trip against a temp DB; assert list is role/owner-scoped and newest-first; assert store.reload() is never triggered by a chat write.
- DB inspection: sqlite3 senpai/data/ingested/chat_history.db '.tables' and
SELECT conversation_id,title,role,updated_at FROM conversations ORDER BY updated_at DESC;.
- End-to-end (scripts/run_web.sh): send a chat turn incl. a /review skill turn â reload the tab â open History drawer â the conversation is listed â click it â transcript AND the review card rehydrate and a follow-up turn continues correctly. Then rename and delete it. Repeat on the manager workspace and confirm role scoping. Kill the backend â confirm chat still streams ephemerally and the drawer shows "History unavailable".
# Commit 3761dfc

This commit shifts the repository away from the old Graph RAG visualization bundle and toward an internal admin portal backed by new FastAPI endpoints and a writable rep-assignment overlay.

## What changed at a glance

The main implementation work falls into four buckets:

1. Admin-facing API routes were added to `senpai/api/server.py`.
2. The in-memory store learned how to upsert `reps` overlay rows by `employee_id`, enabling reassignment without mutating the seed files.
3. A new helper, `store.set_reports_to`, was added to persist manager changes in the gitignored ingested overlay.
4. The old Graph RAG visualization bundle was removed, including the dashboard docs, demo scripts, WebSocket server, and instrumented query wrappers.

## New admin portal API surface

The backend now exposes a set of `/api/admin/*` endpoints in `senpai/api/server.py`.

### Overview and status endpoints

- `GET /api/admin/overview` returns top-level counts for reps, managers, juniors, accounts, deals, open deals, communities, pending knowledge items, LLM token totals, and LLM call totals.
- `GET /api/admin/system-status` returns a runtime snapshot with the current date, retrieval mode, configured LLM endpoints, feature flags, and the number of reps, deals, and overlay files present.
- `GET /api/admin/usage` returns the same usage summary object used elsewhere in the application, including token accounting details.

### People and organization endpoints

- `GET /api/admin/reps` returns every rep, enriched with manager name, team size, login-account presence, open deal count, and top-performer status.
- `GET /api/admin/org` returns a grouped organization view: each manager with their direct reports, plus an unassigned bucket for reps who do not currently report to anyone.
- `POST /api/admin/reps/{employee_id}/reassign` updates a rep's `reports_to` value to a chosen manager.
- `GET /api/admin/accounts` returns login accounts joined to rep names.

### Activity and pipeline endpoints

- `GET /api/admin/activity` merges recent coaching-thread messages and recent daily reports into a single reverse-chronological activity feed.
- `GET /api/admin/pipeline-health` summarizes the grounded community-layer pipeline health, including the worst-performing segments and aggregated failure signals.
- `GET /api/admin/communities` returns the full community report set.
- `GET /api/admin/graph` serializes the underlying NetworkX graph for visualization clients, optionally filtered by `kind`.

### Graph-RAG showcase endpoint

- `POST /api/admin/graph-rag/run` streams a Graph-RAG comparison as SSE.
- The stream emits a start event, graph-side node and edge events, retrieval-trace events, and a final measured comparison between the graph path and the traditional retriever.
- The comparison payload includes latency, context size, estimated tokens, sample records, and explanatory notes for both approaches.

## Data-store changes

The biggest data-model change is in `senpai/data/store.py`.

### Overlay behavior for reps

Previously, overlay rows were simply appended to the seed rows. This commit changes `reps` specifically so overlay rows act like an UPSERT keyed by `employee_id`.

That means:

- If the overlay contains a rep with the same `employee_id` as a seed rep, the overlay row replaces the seed row on read.
- If the overlay contains a brand-new `employee_id`, the rep is appended as a new record.
- Other tables still use additive overlay behavior.

This is what makes editable reporting lines possible without mutating committed seed JSON.

### New reassignment helper

`store.set_reports_to(employee_id, manager_id)` was added to persist manager changes.

It does the following:

- Loads the current rep record.
- Validates that the target rep exists.
- Validates that the target manager exists and has a manager-eligible role (`senior` or `expert`).
- Prevents self-reporting.
- Writes the updated rep into `config.INGESTED_DIR / "reps.json"`.
- Clears the store cache so the change is immediately visible.

The helper returns the updated rep record.

## Auth change

`senpai/api/auth.py` now exposes `list_users()`.

This returns every account in public shape only, meaning:

- username
- role
- employee_id

It intentionally omits password material and is used by the admin portal to show who can sign in.

## Added implementation details in the admin API

The admin routes in `senpai/api/server.py` also introduce a few reusable helpers:

- `_MANAGER_ROLES = ("senior", "expert")` defines which rep roles count as managers.
- `_is_manager(rep)` centralizes that role check.
- `_account_emp_ids()` extracts the set of employee IDs that already have login accounts.
- `_open_deal_count(employee_id)` counts open deals for a rep.
- `_direct_reports(manager_id)` builds the canonical org chart from `reports_to`.
- `_rep_row(rep, accounts)` shapes a rep into the admin-table format.
- `_usage_summary()` wraps the LLM usage reporter.
- `_node_label()` normalizes graph labels for visualization clients.
- `_est_tokens(text)` uses the shared token estimator for the graph-vs-traditional comparison.

## Visualization and Graph-RAG showcase (how it works exactly)

This commit removes the old WebSocket visualization server and replaces it with an admin-page flow built on two APIs:

- `GET /api/admin/graph` for the base graph snapshot.
- `POST /api/admin/graph-rag/run` for live streaming events (SSE).

### 1) Base graph load (static network)

When the admin live page opens, it fetches `GET /api/admin/graph`.

Server behavior:

- Builds the real NetworkX graph via `senpai.graph.build.graph()`.
- Serializes all nodes with key fields (`id`, `kind`, `label`, `degree`, `outcome`, `category`, `industry`).
- Serializes edges as `{source, target, rel}`.
- Returns `{nodes, links, stats}`.

Frontend behavior:

- `web/app/admin/visualization/live/page.tsx` renders this via `ForceGraphView`.
- Node color comes from `kind`; node size uses degree.
- This is the map that later gets highlighted by streaming events.

### 2) Live run start (SSE stream)

When the user presses Run on the live page, frontend calls:

- `graphRagStream(query, onEvent)` in `web/lib/api.ts`.
- It POSTs `{ "query": "..." }` to `/api/admin/graph-rag/run`.
- The response is read as Server-Sent Events using the shared `readSSE` parser.

SSE frame format:

```text
data: {"type":"...", ...}

```

Each frame is decoded from `data:` JSON and passed to the UI event handler.

### 3) Server event generation order

The stream is produced by `_run_graph_rag_stream(query)` in `senpai/api/server.py`.
The event sequence is deterministic:

1. `start`
2. zero or more `node_visited` (community nodes)
3. zero or more `node_visited` (rep nodes)
4. zero or more `edge_traversed` (rep -> deal sample edges)
5. zero or more `retrieved` (real retrieval-trace events)
6. exactly one `comparison`
7. exactly one `done`

### 4) What each event means

- `start`
	- Marks the run beginning and echoes query text.

- `node_visited`
	- For communities: emitted from selected segment reports (`_comm.select`).
	- For reps: emitted from representative graph query rows (`_gq.reps_who_win(min_deals=2)[:5]`).
	- Carries summary metrics (for example `n_deals`, `win_rate`, `won`, `closed`).

- `edge_traversed`
	- Emitted for sampled rep-owned deals (`rel: "OWNS"`).
	- Used by UI to highlight involved nodes.

- `retrieved`
	- Forwarded from retrieval tracing (`senpai.retrieval.trace`).
	- This is the real trace panel data on the live page.

- `comparison`
	- Final measured head-to-head payload with two sides:
		- `graph`: communities + graph path context.
		- `traditional`: semantic/hybrid retrieval context.
	- Both sides include: `chunks`, `context_chars`, `context_tokens`, `latency_ms`, `note`, and `sample`.
	- Token counts are estimated by the same estimator (`_est_tokens`) for both sides, so ratios are apples-to-apples.

- `done`
	- End-of-stream marker.

### 5) Graph side vs traditional side (exact computation)

Graph side in the stream:

- Starts retrieval tracing (`_trace.start()`).
- Selects top communities from `communities.select(query, limit=5)`.
- Runs representative graph query `reps_who_win(min_deals=2)` and keeps top 5.
- Measures elapsed time as `graph_ms`.
- Builds graph context text by concatenating `communities.format_report(segment)`.

Traditional side in the stream:

- Calls `semantic_search(query, corpus="activities", limit=8)` on the same query.
- Measures elapsed time as `trad_ms`.
- Builds context text from retrieved chunk text/snippets.
- Includes retriever mode (`_sem.mode()`) in the label.

Comparison event:

- Uses shared token estimate for both contexts.
- Emits measured latency and context sizes for both pipelines.
- Includes compact samples so the UI can display concrete evidence, not just totals.

### 6) How the live page renders this

`web/app/admin/visualization/live/page.tsx` handles events as follows:

- `node_visited`
	- Appends a traversal row.
	- For `rep` nodes, adds rep id to highlighted node set.

- `edge_traversed`
	- Adds source and target ids to highlighted set.

- `retrieved`
	- Appends raw trace object to the Retrieved (real trace) panel.

- `comparison`
	- Stores payload and renders `ComparisonScorecard`.

Important rendering detail:

- Highlights are id-based against the base graph loaded from `/api/admin/graph`.
- Community labels are shown in the traversal panel, but only graph node ids that exist in the base graph can visually highlight in `ForceGraphView`.

### 7) Why this differs from the removed legacy visualization

Removed legacy path:

- Separate FastAPI app (`senpai/api/visualization_server.py`).
- WebSocket broadcast hub.
- Instrumented query wrappers (`senpai/graph/query_instrumented.py`).
- Standalone HTML dashboard and dedicated docs.

Current path introduced by this commit:

- Same main API service (`senpai/api/server.py`), no separate viz server.
- SSE stream for one run at a time.
- Admin pages consume stream directly.
- Measured Graph-vs-traditional comparison is first-class in the payload.

### 8) Mental model (one run)

1. Load graph once (`/api/admin/graph`) and render network.
2. Submit a query (`/api/admin/graph-rag/run`).
3. Server emits visited nodes/edges and retrieval trace.
4. UI progressively updates traversal and highlights.
5. Server emits final `comparison` scorecard.
6. Server emits `done`; UI stops run.

That is the full visualization loop now implemented by commit `3761dfc`.

## Removed files

The following Graph RAG visualization artifacts were deleted in this commit:

- `GRAPH_VIZ_SUMMARY.md`
- `VISUALIZATION_QUICK_START.md`
- `demo_visualization.py`
- `example_visualization.py`
- `senpai/api/visualization_server.py`
- `senpai/graph/query_instrumented.py`

The practical impact is that the old websocket-based visualization path no longer exists in the repo. Any remaining references to those scripts or docs will need to be updated to the new admin Graph-RAG flow if they are still used anywhere else.

## New script

`scripts/backfill_reports_to.py` was added to populate `reports_to` values for reps that do not already have one.

Its behavior is:

- Scan every rep in the store.
- Skip reps that already have a manager.
- Infer a manager from coaching threads by choosing the most frequent `manager_id`.
- Restrict candidates to real managers (`senior` or `expert`).
- Persist the result through `store.set_reports_to`.

This gives the admin portal a way to start from the current seed data and backfill reporting lines into the ingested overlay.

## Miscellaneous added artifact

`out.txt` was added as a captured test/invocation scratch file containing direct calls into the instrumented graph queries.

It is not part of the runtime code path, but it documents the manual execution pattern that was used while exercising the visualization behavior.

## Net effect of the commit

This commit does two things at once:

- It adds an internal admin surface for inspecting reps, accounts, activity, health, usage, and graph structure.
- It removes the older standalone visualization implementation and replaces the demo story with a server-backed Graph-RAG stream under the admin API.

The most important behavioral change is the new `reps` overlay upsert logic, because that makes manager reassignment durable and non-destructive for seed data.

## Notes for reviewers

- The admin portal routes are explicitly internal-only and currently have no auth gate.
- The reassignment flow depends on the overlay file under `config.INGESTED_DIR`; seed files remain unchanged.
- The Graph-RAG stream is measured, not synthetic: the comparison payload is built from the live retrieval and graph execution on the current query.
# Commit 3761dfc

This commit shifts the repository away from the old Graph RAG visualization bundle and toward an internal admin portal backed by new FastAPI endpoints and a writable rep-assignment overlay.

## What changed at a glance

The main implementation work falls into four buckets:

1. Admin-facing API routes were added to `senpai/api/server.py`.
2. The in-memory store learned how to upsert `reps` overlay rows by `employee_id`, enabling reassignment without mutating the seed files.
3. A new helper, `store.set_reports_to`, was added to persist manager changes in the gitignored ingested overlay.
4. The old Graph RAG visualization bundle was removed, including the dashboard docs, demo scripts, WebSocket server, and instrumented query wrappers.

## New admin portal API surface

The backend now exposes a set of `/api/admin/*` endpoints in `senpai/api/server.py`.

### Overview and status endpoints

- `GET /api/admin/overview` returns top-level counts for reps, managers, juniors, accounts, deals, open deals, communities, pending knowledge items, LLM token totals, and LLM call totals.
- `GET /api/admin/system-status` returns a runtime snapshot with the current date, retrieval mode, configured LLM endpoints, feature flags, and the number of reps, deals, and overlay files present.
- `GET /api/admin/usage` returns the same usage summary object used elsewhere in the application, including token accounting details.

### People and organization endpoints

- `GET /api/admin/reps` returns every rep, enriched with manager name, team size, login-account presence, open deal count, and top-performer status.
- `GET /api/admin/org` returns a grouped organization view: each manager with their direct reports, plus an unassigned bucket for reps who do not currently report to anyone.
- `POST /api/admin/reps/{employee_id}/reassign` updates a rep’s `reports_to` value to a chosen manager.
- `GET /api/admin/accounts` returns login accounts joined to rep names.

### Activity and pipeline endpoints

- `GET /api/admin/activity` merges recent coaching-thread messages and recent daily reports into a single reverse-chronological activity feed.
- `GET /api/admin/pipeline-health` summarizes the grounded community-layer pipeline health, including the worst-performing segments and aggregated failure signals.
- `GET /api/admin/communities` returns the full community report set.
- `GET /api/admin/graph` serializes the underlying NetworkX graph for visualization clients, optionally filtered by `kind`.

### Graph-RAG showcase endpoint

- `POST /api/admin/graph-rag/run` streams a Graph-RAG comparison as SSE.
- The stream emits a start event, graph-side node and edge events, retrieval-trace events, and a final measured comparison between the graph path and the traditional retriever.
- The comparison payload includes latency, context size, estimated tokens, sample records, and explanatory notes for both approaches.

## Data-store changes

The biggest data-model change is in `senpai/data/store.py`.

### Overlay behavior for reps

Previously, overlay rows were simply appended to the seed rows. This commit changes `reps` specifically so overlay rows act like an UPSERT keyed by `employee_id`.

That means:

- If the overlay contains a rep with the same `employee_id` as a seed rep, the overlay row replaces the seed row on read.
- If the overlay contains a brand-new `employee_id`, the rep is appended as a new record.
- Other tables still use additive overlay behavior.

This is what makes editable reporting lines possible without mutating committed seed JSON.

### New reassignment helper

`store.set_reports_to(employee_id, manager_id)` was added to persist manager changes.

It does the following:

- Loads the current rep record.
- Validates that the target rep exists.
- Validates that the target manager exists and has a manager-eligible role (`senior` or `expert`).
- Prevents self-reporting.
- Writes the updated rep into `config.INGESTED_DIR / "reps.json"`.
- Clears the store cache so the change is immediately visible.

The helper returns the updated rep record.

## Auth change

`senpai/api/auth.py` now exposes `list_users()`.

This returns every account in public shape only, meaning:

- username
- role
- employee_id

It intentionally omits password material and is used by the admin portal to show who can sign in.

## Added implementation details in the admin API

The admin routes in `senpai/api/server.py` also introduce a few reusable helpers:

- `_MANAGER_ROLES = ("senior", "expert")` defines which rep roles count as managers.
- `_is_manager(rep)` centralizes that role check.
- `_account_emp_ids()` extracts the set of employee IDs that already have login accounts.
- `_open_deal_count(employee_id)` counts open deals for a rep.
- `_direct_reports(manager_id)` builds the canonical org chart from `reports_to`.
- `_rep_row(rep, accounts)` shapes a rep into the admin-table format.
- `_usage_summary()` wraps the LLM usage reporter.
- `_node_label()` normalizes graph labels for visualization clients.
- `_est_tokens(text)` uses the shared token estimator for the graph-vs-traditional comparison.

## Visualization and Graph-RAG showcase

Although the old standalone visualization package was removed, this commit still adds a Graph-RAG showcase path under the admin API.

The new streaming flow does this:

1. Selects graph communities relevant to the query.
2. Runs a representative graph query and emits node/edge events.
3. Drains the retrieval trace and forwards it as stream events.
4. Runs the semantic retriever on the same query.
5. Compares both paths using the same token estimator.

The intended effect is a live, measurable comparison between graph-grounded retrieval and traditional retrieval without needing the deleted visualization server.

## Removed files

The following Graph RAG visualization artifacts were deleted in this commit:

- `GRAPH_VIZ_SUMMARY.md`
- `VISUALIZATION_QUICK_START.md`
- `demo_visualization.py`
- `example_visualization.py`
- `senpai/api/visualization_server.py`
- `senpai/graph/query_instrumented.py`

The practical impact is that the old websocket-based visualization path no longer exists in the repo. Any remaining references to those scripts or docs will need to be updated to the new admin Graph-RAG flow if they are still used anywhere else.

## New script

`scripts/backfill_reports_to.py` was added to populate `reports_to` values for reps that do not already have one.

Its behavior is:

- Scan every rep in the store.
- Skip reps that already have a manager.
- Infer a manager from coaching threads by choosing the most frequent `manager_id`.
- Restrict candidates to real managers (`senior` or `expert`).
- Persist the result through `store.set_reports_to`.

This gives the admin portal a way to start from the current seed data and backfill reporting lines into the ingested overlay.

## Miscellaneous added artifact

`out.txt` was added as a captured test/invocation scratch file containing direct calls into the instrumented graph queries.

It is not part of the runtime code path, but it documents the manual execution pattern that was used while exercising the visualization behavior.

## Net effect of the commit

This commit does two things at once:

- It adds an internal admin surface for inspecting reps, accounts, activity, health, usage, and graph structure.
- It removes the older standalone visualization implementation and replaces the demo story with a server-backed Graph-RAG stream under the admin API.

The most important behavioral change is the new `reps` overlay upsert logic, because that makes manager reassignment durable and non-destructive for seed data.

## Notes for reviewers

- The admin portal routes are explicitly internal-only and currently have no auth gate.
- The reassignment flow depends on the overlay file under `config.INGESTED_DIR`; seed files remain unchanged.
- The Graph-RAG stream is measured, not synthetic: the comparison payload is built from the live retrieval and graph execution on the current query.