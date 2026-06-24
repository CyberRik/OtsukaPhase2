# Resolution, grounding & the reasoning router

Two mechanisms protect Senpai's core promise — *rather miss than fabricate the
wrong customer's facts* — and keep it fast:

1. **Customer resolution** (`senpai/data/store.py`) — turning a typed name or a
   free-text message into a customer, **preserving ambiguity as a first-class
   state** so Senpai never silently attributes the wrong company's history.
2. **The reasoning router** (`senpai/llm/routing.py`) — deciding, per turn,
   whether the model should *think* (REASONING mode) or answer immediately (FAST
   mode), so latency is spent only where quality needs it.

This doc is the deep reference for both. The bridge that wires them is in
[`llm_bridge.md`](llm_bridge.md).

---

## Part 1 — Customer resolution & grounding

### The alias index

`_alias_index()` maps every normalized name/alias key → the **set** of customer
ids that answer to it. The set is the whole point: a key owned by more than one
customer is **ambiguous**, and callers must not guess. Keys come from
`name_forms()` (JA name, English/romaji forms) plus authored `customer_aliases()`;
keys shorter than 2 normalized chars are dropped.

### Resolution result type

```python
@dataclass
class CustomerResolution:
    status: "resolved" | "ambiguous" | "not_found"
    query: str
    customer: dict | None              # set only when resolved
    candidates: list[CustomerCandidate]  # set only when ambiguous
```

`CustomerCandidate` carries `customer_id`, `name`, and the `matched_aliases` that
caused the hit — so the UI can show *why* each candidate is a candidate.

### `resolve_customer_detailed(query)` — the whole query is the name

The primary resolver, tried in confidence order:

1. **exact id** (`get_customer(q)`) → resolved.
2. **exact alias key** (`_alias_index()[norm(q)]`) → resolved if it maps to one
   customer, **ambiguous** (with all candidates) if it maps to several.
3. **loose name match** (`find_customer_by_name`) → resolved.
4. otherwise **not_found**.

`resolve_customer(query)` is the thin wrapper tools/coach use — it returns the
customer **or None** (None on empty, unknown, *or ambiguous*), never a guess.

### Matching inside free text — the word-boundary rule

A message like "create a quotation for akebono" isn't a bare name; the customer
token is buried in an action phrase. `_key_in_text(key, low_text)` decides whether
an alias occurs in text, with a critical asymmetry:

```python
def _key_in_text(key, low_text):
    if key.isascii():
        return re.search(r"\b" + re.escape(key) + r"\b", low_text) is not None  # word boundary
    return key in low_text                                                       # substring
```

- **ASCII / romaji keys require word boundaries** — so `new` doesn't match inside
  `news`, and `canon` doesn't match inside `canonical`. (Latin words run together
  with spaces; bare substring matching invents customers.) This fixed a live
  `news → new` false match found during stress testing.
- **Japanese keys keep substring matching** — JA has no word boundaries and names
  are contiguous (`村田印刷` must match inside `村田印刷さん`).

Built on that:

| Function | Returns | Use |
|---|---|---|
| `match_customer_in_text(text)` | the customer (longest match wins; **None if the winning form is ambiguous**) | unique extraction |
| `ambiguous_match_in_text(text)` | the candidate records when the longest match maps to >1 customer | surface-the-ambiguity counterpart |
| `resolve_customer_in_text(text)` | a full `CustomerResolution` (resolved/ambiguous/not_found) over text | the research path |

`resolve_customer_in_text` is what fixed **`/research create a quotation for
akebono`** reporting "Internal Records: not_found" and falling through to web
search — it now returns *ambiguous* (3 あけぼの companies), so research reaches
internal records first. Longest-match-wins also means "Aozora Services" beats
"Aozora" and "大和商事システム" beats "大和".

### Fallback resolution — fuzzy + company-name extraction

When exact/alias finds nothing:

- `extract_company_names_from_text(text)` pulls likely company tokens via
  legal-form patterns (`株式会社…`, `…（株）`) and suffix patterns (`商事`, `印刷`,
  `電機`, …), longest-first, to retry through the exact/alias resolver.
- `fuzzy_match_customer_in_text(text, threshold=0.72)` slides a window the length
  of each **unambiguous** alias key over the text and scores `difflib`
  character similarity. Keys <4 chars are skipped to avoid false positives.
  Returns `(customer, best_score)` — `customer` is None below threshold.

### The trust model — confidence decides ground vs ask

This is the rule the whole product hangs on (`coach/context.build_commentary_context`):

| Confidence | Source | Action |
|---|---|---|
| **high** | exact id / exact alias / deal id | **auto-ground** |
| **medium** | fuzzy match | surface as a `near_miss` candidate — **never ground** |
| **low** | name extracted from free text | surface as a candidate — **never ground** |

This is what fixed the **"okamoto electronics" false grounding**: a fuzzy 0.875
match to 岡本電機/D048 used to silently ground. Now only high-confidence grounds;
medium/low surface candidates, and the prompt gets explicit near-match copy
("NEAR-MATCH ONLY — … NOT an exact match") so the LLM can't paper over it.

### `/api/customers/smart-resolve` — deterministic → fuzzy → LLM rank

The Workspace `/account` picker uses a three-stage resolver that **only ever
re-orders or asks; it never fabricates**:

1. **Deterministic** (`resolve_customer_detailed`) — exact/alias. If resolved,
   done (and `suggested_id` is that customer).
2. **Fuzzy near-miss** — when not_found, enrich with `difflib` candidates
   (threshold 0.68, top-5, only unambiguous keys) so a typo still offers choices.
3. **LLM ranking** — when ≥2 candidates and the LLM is up, ask it to pick the
   single best `customer_id` (constrained 16-token, `no_think=True` answer; only a
   `C\d+` token is extracted). It **re-sorts** candidates and sets `suggested_id`
   — it can reorder the picker but can't invent a customer not already in the
   deterministic/fuzzy candidate set. A router/LLM fault is swallowed and the
   deterministic order stands.

The endpoints that *resolve* (`/api/customers/resolve`) vs *resolve-and-rank*
(`/api/customers/smart-resolve`) are separate so callers choose how much help
they want.

---

## Part 2 — The reasoning router (FAST vs REASONING)

### Why it exists

The served model is a **reasoning distill** — it emits a `<think>…</think>` phase
before the answer. Latency testing showed that phase is **pure overhead** for
retrieval/provenance answers (restating grounded records) but **beneficial** for
numeric interpretation and cross-signal synthesis. The router spends reasoning
latency only where it buys quality.

### The mechanism — how "no_think" actually works

The current `llama-server` build's chat template has **no `enable_thinking`
variable** and ignores `reasoning_effort` / `/no_think`. The only lever that
works is **prefilling the assistant turn with an already-closed, empty think
block** (`senpai/llm/client.py`):

```python
_NO_THINK_PREFILL = {"role": "assistant", "content": "<think>\n\n</think>\n\n"}
def _prep(messages, no_think):
    return [*messages, _NO_THINK_PREFILL] if no_think else messages
```

This makes the distill skip its reasoning phase and answer immediately — the
dominant latency win for short conversational outputs (Senior Commentary, account
reads). When reasoning *is* allowed, the client reconstructs the think span from
whichever shape the backend uses: inline `<think>` in `content` (vLLM/ollama) or a
separate `reasoning_content` delta field (llama.cpp), via `_delta_reasoning`. The
answer is always split on `</think>` so only user-facing text streams.

### The decision interface

The Assistant **asks** a router; it never decides itself. The interface is
provider-agnostic so a classifier / LLM-judge / Atlas router can be swapped in
later via `get_reasoning_router()` with no change to the execution loop.

```python
@dataclass
class RoutingRequest:   message: str; role: str; tools_used: list[str]; rounds: int
@dataclass
class RoutingDecision:  think: bool; reason: str; confidence: float
```

Every decision carries a **human-readable `reason`** (observability/trust), and
the bridge emits it to the UI as a `routing` event (`mode: "reasoning" | "fast"`).

### `DeterministicReasoningRouter` — the rules (order matters)

| Priority | Condition | Decision | Confidence |
|---|---|---|---|
| 1 | a **HIGH_REASONING tool** was used (`score_deal_health`, `list_at_risk_deals`, `team_pipeline_overview`, `team_report_digest`, `rep_coaching_focus`, `find_similar_deals`) | **REASONING** | 0.9 |
| 2 | **≥2 distinct tools** used (multi-tool synthesis) | **REASONING** | 0.75 |
| 3 | query intent matches `_HIGH_INTENT` (なぜ/理由/矛盾/推移/比較/risk/why/synthesis…) | **REASONING** | 0.6 |
| 4 | one or more tools, all retrieval/provenance (`search_knowledge`, `query_spr`, …) | **FAST** | 0.85 |
| 5 | no tools at all | **FAST** | 0.5 |

So a `score_deal_health` answer (the numeric "77/100" interpretation) thinks; a
`search_knowledge` answer (restating a grounded record) does not.

### Where routing applies

Crucially, routing governs **only the final synthesis round**. The bridge's tool
loop runs like this (`llm/client.py:stream_chat_turn`):

- **Tool-selection rounds** stay FAST regardless (validated correct without
  reasoning, and this is where the bulk of latency lives — `TOOLLOOP_NO_THINK`).
- When a round produces **no tool call**, that's the answering round →
  `_route_final_answer` asks the router, emits the `routing` event, and streams
  the answer in the chosen mode.
- A router fault is caught and falls back to the static `TOOLLOOP_NO_THINK`
  default — a routing bug can never break a turn.

### Config flags

| Env | Default | Effect |
|---|---|---|
| `SENPAI_REASONING_ROUTER` | `deterministic` | router impl; `off` reverts to static behaviour |
| `SENPAI_TOOLLOOP_NOTHING` (`TOOLLOOP_NO_THINK`) | on | tool-selection rounds skip `<think>` |
| `SENPAI_NARRATE_THINK` (`NARRATE_THINK`) | off | let the deal-level senior read think (off = fast live path) |
| `MAX_TOOL_ROUNDS` | 4 | tool-loop budget before a forced answer |
| `LLM_NARRATE_MAX_TOKENS` | 600 | narration length cap |
| `BASE_URL` / `MODEL` | `127.0.0.1:8765/v1` / `exp3` | primary endpoint |
| `FALLBACK_BASE_URL` / `FALLBACK_MODEL` | `…:8766` / `toolmind_exp3_final` | used unless `allow_fallback=False` pins primary |

---

## Why this design holds up

- **Ambiguity is data, not failure.** Every resolver returns a *status*; the UI
  asks instead of guessing, and a near-match is labelled as such to the model.
- **Latin vs Japanese matching is handled explicitly** — the single source of the
  past false-customer bugs, now a one-function rule with documented cases.
- **The model can re-rank but not invent** — LLM resolution only sorts an
  already-grounded candidate set.
- **Routing is explainable and fail-safe** — a deterministic rule set with a
  reason on every decision, swappable behind one factory, and wrapped so a fault
  degrades to fast rather than breaking the turn.
