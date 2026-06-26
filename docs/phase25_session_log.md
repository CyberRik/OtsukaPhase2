# Phase 2.5 — session log: real tools, dynamic UI, latency & router/model evals

This doc captures work from the Phase 2.5 build session that isn't covered by the
surface/engine docs. Three buckets: **features wired live**, **bugs fixed**, and —
the substantive part — **the latency investigation and the two offline evals**
(Atlas intent router, model decomposition) including their measured results and
the decisions that came out of them.

The standing docs ([`resolution_and_routing.md`](resolution_and_routing.md),
[`llm_bridge.md`](llm_bridge.md), [`workspace.md`](workspace.md)) describe the
*current* design. This doc is the **why** behind the recent changes and the
**evidence** for the architectural calls we did *not* make.

---

## 1. Features wired to real behaviour

### 1.1 `schedule_meeting` → real Google Calendar (two-step confirm)
- New `senpai/tools/gcal.py`: `create_event(...) -> (ok, link)`, OAuth via
  `credentials.json` / `token.json` resolved from repo **root**
  (`_ROOT = Path(__file__).resolve().parents[2]`). Both creds are gitignored
  (`/credentials.json`, `/token.json`).
- `senpai/tools/impl.py::schedule_meeting(..., confirm: bool = False)` is now a
  **two-step** tool: with `confirm=False` it returns a *draft* (human reads it
  back); with `confirm=True` it lazily imports `gcal` and books, falling back to
  `（シミュレーション）` if the calendar call fails. Schema in
  `senpai/tools/schemas.py` gained the `confirm` boolean + two-step description.
- Rationale: outward-facing action (creates a real event) → never fire on the
  first turn; the model must surface the draft and get a confirm.

### 1.2 Workspace "quick examples" → live LLM chat
- `web/components/workspace/workspace.tsx`: example buttons now call
  `runChat(loc.engineNote)` instead of the old `runReview` (which returned a
  hardcoded artifact). The examples are real streamed turns now.

### 1.3 Junior home stats made dynamic
- `/api/knowledge/principles` counts gained
  `"pending": sum(1 for p in ps if p["status"] != "approved")`.
- `web/app/junior/page.tsx`: `counts` is now
  `{pTotal, pPending, iTotal, iDraft, two}`; each stat shows the total plus a
  pending/draft sub-count instead of the old hardcoded "approved principles /
  coaching items / both seniors agree" and "32 reviews / 9-week streak".
- i18n keys added in `web/lib/i18n.tsx` (`jhome.pending`, `jhome.draft`,
  `jhome.principlesApproved` → 原則/Principles); fallback counts in `web/lib/api.ts`.

### 1.4 Deal dropdown grounding + Japanese names
- `runChat(text, deal?)` threads the chosen deal and appends a grounding
  parenthetical: `（対象案件: ${d.deal_id} ${d.customer}）`. The user message
  carries `dealLabel`, the assistant message stores the grounded text.
- Dropdown option and badge now render the **raw Japanese** customer name
  (`{d.deal_id} · {d.customer}`) instead of being passed through `customerText`,
  matching what the LLM actually synthesizes.

---

## 2. Bugs fixed

| Symptom | Root cause | Fix |
|---|---|---|
| `/account marusan foods` → "Customer not found" | Bridge wasn't running on :8000; frontend fell back to offline `not_found` | Start the bridge (data was fine all along) |
| "setup a meeting" narrated a fake `[ツール呼び出し]` instead of calling the tool | `TOOLLOOP_NO_THINK` empty-`<think>` prefill in the **selection** round suppressed tool emission | `senpai/llm/client.py`: selection rounds use `_prep(convo, False)` (keep think) + prompt directive "call tools directly, don't narrate". A/B proved: NOTHINK_ON → 0 tools, NOTHINK_OFF → `schedule_meeting` |
| Reasoning leaked into the response box (`<analysis>…`) | `_strip_reasoning` only handled `<think>` | `server.py`: generalized `_THINK_OPEN`/`_THINK_CLOSE` to also match `think(ing)`/`analysis`/`reasoning`; routed research summarizers through `_strip_reasoning` |
| Slash picker `TypeError: Cannot read properties of undefined (reading 'cmd')` | Stale `active` index when the filtered list shrank | `activeIdx` clamp + `useEffect` reset; Enter guards `const sel = filtered[activeIdx]; if (sel) …` |
| `/research about C14` → "Internal Records: not_found" | Resolvers recognized `D###` deal ids but not `C##` customer ids | `senpai/data/store.py`: added `_CUSTOMER_ID_RE` + `_customer_id_in_text`; `match_customer_in_text` checks customer id first |
| Retrieval silently fell back to BM25 (no dense vectors) | fastembed cache was corrupt — tokenizer only, no ONNX weights | Cleared + re-downloaded the cache; for the offline Atlas eval, `eval_intent_router.py` falls back to `sentence-transformers` with the **same** MiniLM model |

> A note for the record: one "C14 not_found" alarm during testing was a **false
> alarm** — Windows `curl` mangled the UTF-8 Japanese POST body to `?`. The Python
> harnesses send proper UTF-8 (`PYTHONUTF8=1`, JSON via file + `--data-binary`).

---

## 3. Latency investigation (prompt + routing, no model change)

Reasoning-mode turns were slow (~395s end-to-end on a multi-tool research turn).
Breakdown from instrumentation:

- **Tool-selection round**: ~23s for ~205 tokens (the `<think>` was only ~78
  chars) → capping selection-think buys ~nothing. Left intact.
- **Final synthesis**: ~230s — **this dominates**. The lever is *input* and
  *output* size, not the think budget.

Changes that landed:

1. **Parallel tool calls.** `_junior_system` / `_manager_system` / `_research_system`
   now instruct: when several independent lookups are needed, emit them in **one
   turn** (「独立した複数の情報が必要なときは…1ターンでまとめて並行呼び出し」).
   Fewer sequential selection rounds.
2. **Router rule: all-retrieval multi-tool → FAST.** `senpai/llm/routing.py` rule #2
   is now `if len(distinct) >= 2 and (distinct - LOW_REASONING_TOOLS):` — a turn
   that only fans out over retrieval tools doesn't need THINK synthesis.
3. **`search_notes` clamp.** `senpai/tools/impl.py` clamps `limit` to ≤6
   (`max(1, min(limit, 6))`) — caps the dominant synthesis input (and thus output).

**Result: ~395s → ~256s.** After this we concluded prompt/routing optimization was
near its limit and the remaining ~230s synthesis cost is a *model* problem, which
motivated the model-decomposition eval (§5).

---

## 4. Atlas intent-router evaluation (offline feasibility — NOT shipped)

**Question.** Could a dedicated lightweight router ("Atlas") replace the rule-based
routing — deciding *destination* (research/tool/chat), *which tool*, and *mode*
(fast/think) — using the project's existing multilingual MiniLM embeddings (no GPU,
no LLM call)? Constraint from the user: Atlas must **route only**, never answer.

**Harness.** `scripts/eval_intent_router.py` — 63 hand-labeled bilingual queries,
tiny `LogisticRegression` heads on MiniLM embeddings, 5-fold CV, compared against
the **current rule baselines** (`_is_research_intent`, `DeterministicReasoningRouter`).
Run: `python scripts/eval_intent_router.py` (fastembed + sklearn, no endpoint).

**Results.**

| Head | Classifier | Rule baseline | Read |
|---|---|---|---|
| destination (research/tool/chat) | **~0.82** | research-detection on par | usable but not a clear win |
| mode (fast/think) | ~tie | `DeterministicRouter` ≈ same | **rules already as good** |
| tool_hint (which tool) | **~0.49** | — | **not separable** in MiniLM space |

**Decision: do NOT build Atlas wholesale.** The mode head ties the existing
deterministic router (no reason to add a model), and tool_hint at ~0.49 is too
unreliable to pick tools — that job stays with the 27B's own tool selection. The
destination head (~0.82) is the only place a classifier might help, and not enough
to justify a new always-on component. The rules win on simplicity. (Caveat baked
into the script's output: tiny hand-labeled set → this measures *feasibility /
separability*, not production accuracy.)

---

## 5. Model decomposition: smaller synthesis model (in progress)

**Question.** The ~230s synthesis dominates. Can the **final grounded synthesis** be
served by a smaller model (Qwen3-8B) without materially hurting grounding/quality,
for a big latency win — while the 27B keeps doing tool selection?

**Methodology (the part that has to be right).** `scripts/bench_synthesis.py`
**freezes the tool context**: it runs the 27B's selection rounds + executes tools
**once**, then feeds the *identical* post-tool context to both synthesis models.
That isolates the synthesis-model variable (no tool-selection nondeterminism).
- Control: `27B (select) → tools → 27B (synthesis)`
- Candidate: `27B (select) → tools → 8B (synthesis)` on the **same frozen context**
- Both arms use the same `no_think` flag from the router (like-for-like).
- Metrics: latency, prompt/completion tokens, decode tok/s, **grounding fidelity**
  (every ¥amount / C-id / D-id / date / source-id in the answer must trace to the
  frozen context — anything that doesn't is a candidate fabrication), provenance
  (cited PB/P ids exist), and side-by-side dumps for blind quality review.
- Run: `python scripts/bench_synthesis.py --candidate-base http://127.0.0.1:8766/v1 --candidate-model qwen3-8b --queries N [--judge]`

**Round 1 — bf16 Qwen3-8B vs Q4_K_M 27B (4 FAST queries):**

| Arm | avg latency | tokens | decode | grounding fidelity |
|---|---|---|---|---|
| 27B (Q4_K_M) | 64.9s | 695 | 10.7 tok/s | 0.957 |
| 8B (bf16) | 58.5s | 772 | 13.2 tok/s | 0.961 |

**Speedup: only ~1.11×.** Why: decode is **memory-bandwidth-bound on bytes/token**,
and bf16-8B (~16GB) moves about the same bytes per token as Q4-27B (~14GB) — so
parameter count alone doesn't buy speed. **But grounding/quality came out at
parity** (0.961 vs 0.957). That's the important signal: an 8B *can* do the
restatement-grade synthesis faithfully; we just need it **quantized** to shrink
bytes/token.

**Round 2 (pending): Q4_K_M Qwen3-8B (~5GB → ~3× fewer bytes/token).** Expected
~3× synthesis speedup at the same grounding parity. Downloading
`Qwen3-8B-Q4_K_M.gguf` from `Qwen/Qwen3-8B-GGUF` to the GPU box, serving via
llama-server on **:8766** (alias `qwen3-8b`, `-fa on -ctk q8_0 -ctv q8_0 -c 16384
--parallel 2 --cont-batching`), then re-running the bench. This is the only open
thread from the session.

> Serving seam already exists: `senpai/llm/client.py` has `client` (primary
> `BASE_URL` :8765) and `fallback_client` (`FALLBACK_BASE_URL` :8766 /
> `FALLBACK_MODEL`). If round 2 validates, wiring the 8B as the synthesis model is
> a config change at that seam, not new plumbing.

---

## 6. Operational notes (serving, tunnels, logs)

- **Two models coexist on the GB10 box** (no OOM): 27B on :8765, 8B on :8766.
- **Both are reached from this Windows box via SSH tunnels** with keepalive
  (`ServerAliveInterval`). Tunnels die when the Claude Code session that launched
  them tears down — re-establish before the bridge can reach the model.
- **Serve scripts on the box** must `source` the venv activate so launched servers
  inherit PATH (e.g. vLLM's flashinfer JIT needs `ninja`); detached `ssh ... &`
  launches die silently — run the serve in the *foreground* of a background task.
- **Logs:** model servers log on the box (27B
  `~/Desktop/toolcallLM/qwen3/llama-server.log`, 8B serve `~/Desktop/qwen3-8b-gguf/serve.log`,
  download `~/Desktop/qwen3-8b-gguf/download.log`); background commands launched
  here stream to `…/tasks/<id>.output`; the uvicorn bridge logs to whatever
  terminal/task started it (`curl http://localhost:8000/api/health` for a quick
  liveness check).
- **Windows shell + UTF-8:** never send Japanese JSON bodies through `curl` on
  PowerShell (mangled to `?`). Use the Python harnesses (`PYTHONUTF8=1`, JSON via
  file + `--data-binary`).

---

## 7. Artifacts added this session

- `senpai/tools/gcal.py` — real Google Calendar booking.
- `scripts/eval_intent_router.py` — Atlas feasibility eval (§4).
- `scripts/bench_synthesis.py` — model-decomposition A/B with frozen tool context (§5).
- Box: `~/Desktop/qwen3-8b-gguf/serve_8b_gguf.sh` (llama-server, Q4 GGUF, :8766);
  `~/Desktop/qwen3/serve_8b.sh` (vLLM bf16, round-1).
