# The LLM bridge — streaming, routing, grounding

`senpai/api/server.py` is the FastAPI bridge between the Next.js front end and
the deterministic Senpai engines + the local LLM. It exposes the JSON endpoints
the UI reads (`/api/health`, `/api/dashboard`, `/api/account/{id}`, …) and the
**SSE streaming** endpoints that power the Workspace and the chat surfaces.

This doc covers the streaming contract, conversation memory, the routing logic,
the resolution trust model, and the LLM serving setup. The front-end side is in
[`workspace.md`](workspace.md).

---

## Why a streaming bridge

Senpai's outputs are two layers stacked together:

1. a **deterministic record** — health bands, sections, source IDs — computed by
   the Python engines (`coach/`, `health`, `store`), and
2. a **streamed senior read / synthesis** — the LLM's grounded narration over
   that record.

The bridge streams both so the deterministic layer renders instantly and the LLM
narration fills in live. The same SSE channel also carries *resolution* and
*source* events, so the UI can show provenance as it happens.

---

## SSE event protocol

All streaming endpoints emit newline-delimited `data:` frames via `_sse(obj)`.
The event `type` discriminates them:

| `type` | Meaning |
|---|---|
| `start` | stream opened; carries `endpoint` + `conversation_id` |
| `artifact_meta` | deterministic header (band, entity) for the card |
| `context` | the resolved focus context being used |
| `resolve` | resolution outcome for the turn |
| `source` | one internal source consulted (label, status, count) |
| `web` | a web citation (research only, labelled fallback) |
| `delta` | a chunk of streamed LLM text |
| `answer` | the final assembled answer |
| `routing` | which path handled the turn (chat vs research) |
| `tool` | a tool call fired in the chat loop (name + args + result) |
| `awaiting_choice` | ambiguous — UI must show a candidate picker, **no read runs** |
| `done` | stream complete |
| `unavailable` | the engine ran but had nothing grounded to say |
| `error` | failure (e.g. LLM endpoint down) |

`_strip_reasoning` removes the model's chain-of-thought before any `delta` is
emitted, so only the final narration reaches the UI.

---

## The three streaming endpoints

### `coach/narrate` (the `/review` senior read)
- Looks up / builds a coach context keyed by `conversation_id` (`_COACH_CONTEXTS`).
- When grounded, **seeds chat focus** (`_seed_chat_focus`) so later bare turns
  inherit the customer.
- **Short-circuits on ambiguity**: if there's no customer context but there *are*
  ambiguous candidates, it emits `awaiting_choice` then `done` and runs **no LLM
  read** — the senior never speaks about a deal the user hasn't disambiguated.

### `account/commentary` (the `/account` read)
- Takes a `conversation_id` param, streams the account read, and seeds focus.

### `research_stream` (the `/research` pipeline)
- Resolves the customer, emits a **source ledger** (`_source_event`) for each
  internal record consulted, then the grounded answer, then any **web** citations
  as an explicitly labelled fallback.
- **Internal-records-first**: when `resolution.status == "not_found"`, it retries
  with `store.resolve_customer_in_text(message)` (whole-string resolution) before
  ever touching the web — this fixed `/research create a quotation for akebono`
  wrongly reporting "Internal Records: not_found" and web-searching.

---

## Conversation memory

Two per-conversation caches, both keyed by `conversation_id` (the Workspace's
single `threadId`):

```python
_CHAT_CONTEXTS: dict[str, dict]   # conversation_id -> {customer_id, customer, deal_id}
_COACH_CONTEXTS: dict[str, dict]  # conversation_id -> {deal_id, note, r, context_text, meta}
_RESEARCH_CONTEXTS: dict[str, dict]
```

`_seed_chat_focus(conversation_id, customer_id, customer, deal_id)` is the bridge
between skills and chat: when a `/review` or `/account` turn resolves an entity,
its focus is written into `_CHAT_CONTEXTS`, so a later bare follow-up ("what
should I do about this?") stays scoped to the same customer **without the user
re-typing the name**. The focus is always the entity the skill already resolved
(or the deal's own customer) — never a name guess. If only a `deal_id` is known,
the customer is derived from the deal.

---

## Routing: chat vs research vs follow-up

A bare turn into `/api/chat` is routed deterministically before any LLM loop:

- **`_is_followup(message, has_context)`** — short question, has context, matches
  `_FOLLOWUP_RE` (English question/topic cues *and* Japanese continuation cues
  like 次／何を／リスク／決裁／直近), and is **not** a deal id or a research
  prefix → treated as a follow-up on the focused account.
- **`_is_research_intent(message)`** — has a research cue (English prefixes or
  Japanese cues like について教えて／を調べて／リサーチ) **and** names a customer
  we actually have (`resolve_customer_detailed(...).status in {resolved,
  ambiguous}`). Only then does it auto-route to the source-grounded research
  pipeline. This narrowness is deliberate: a coaching question like
  "値引きについて教えて" (tell me about discounting) must **not** get hijacked
  into customer research.
- **Otherwise** → the LLM **tool-calling loop** (junior or manager tool set).

---

## The resolution trust model

Customer/deal resolution drives whether Senpai grounds or asks. The cascade
(`store.resolve_customer_detailed`, `coach/context.build_commentary_context`):

| Confidence | Match type | Action |
|---|---|---|
| **high** | exact id / alias / deal id | **auto-ground** |
| **medium** | fuzzy | surface as a candidate (`near_miss`), **never ground** |
| **low** | name extracted from free text | surface as a candidate, **never ground** |

This is what fixed the **"okamoto electronics" false grounding**: a Tier-2 fuzzy
match (0.875) to 岡本電機/D048 used to silently ground. Now only high-confidence
grounds; medium/low surface candidates — so the UI shows *both* Okamoto companies
and the user picks. `build_commentary_context` adds explicit near-match prompt
copy ("NEAR-MATCH ONLY — … NOT an exact match") so the LLM can't paper over it.

### Word-boundary matching (`store._key_in_text`)

ASCII / romaji aliases require word boundaries (`\bkey\b`); non-ASCII (Japanese)
keys use substring (Japanese has no word boundaries). Used by
`match_customer_in_text`, `ambiguous_match_in_text`, and
`resolve_customer_in_text`. This fixed a "**news**" → "**new**" substring false
match found during stress testing. (Known residual: a bare word "new" still
collides with a ニュー seed alias and surfaces as *ambiguous* — safe, but the root
cause is an over-generic seed alias, not the matcher.)

`resolve_customer_in_text(text)` finds a customer named anywhere in free text
while **preserving ambiguity** (returns resolved / ambiguous / not_found), so the
research pipeline can resolve "create a quotation for akebono" without losing the
3-way ambiguity.

---

## The tool-calling loop

Bare chat that isn't a follow-up or research runs the LLM tool loop with a
role-scoped system prompt (`_junior_system` / `_manager_system`) and tool set.
Tools are deterministic functions over the real SPR data — e.g.
`score_deal_health`, `find_deals` (schema-driven faceted search),
`morning_briefing`. Each tool call is streamed to the UI as a `tool` event so the
chat shows a grounded **tool ledger**. When the model needs no tool it answers
plainly (the UI shows a "General answer (no tools)" badge) — this is why **normal
conversation still works** in the Workspace, not just tool calls.

---

## LLM serving setup

The model is served by `llama.cpp`'s `llama-server` on the GPU box:

- **Model:** `Qwen3.6-27B-Claude-Opus-Reasoning-Distilled-Q4_K_M.gguf`
- **Host:** `team-a@100.101.186.29:8765` (Tailscale)
- **Reachable from Windows ONLY via SSH tunnel:**
  `ssh -N -L 8765:127.0.0.1:8765 team-a@100.101.186.29`
- `.env` points the bridge at `127.0.0.1:8765`.
- **Launch the bridge** with `SENPAI_USE_LLM=1 SENPAI_TODAY=2026-06-16`.
- **Launch the model:**
  `cd ~/Desktop/toolcallLM/qwen3 && setsid bash -c './serve_gguf.sh > llama-server.log 2>&1' </dev/null &`

`serve_gguf.sh` runs with `-ngl 999 -fa on -ctk q8_0 -ctv q8_0 -c 32768
--parallel 4 --cont-batching`. The 16-tool junior schema needs ~2153 tokens, so
under GPU contention the KV footprint can be reduced (`-c 8192 --parallel 2` =
4096 tok/slot) and still serve the schema.

**Troubleshooting** (per the [LLM connectivity](../) notes): a "Connection error"
on the bridge almost always means (a) the SSH tunnel dropped, or (b) the shared
GPU is **OOM** — another team's process can hold most of the GB10's ~128 GB,
causing `llama-server` to load, serve, then `Aborted (core dumped)` ~18 s later.
Check the tunnel and `nvidia-smi` before touching code.

---

## Key functions

| Symbol | Role |
|---|---|
| `_sse` / `_strip_reasoning` | frame encoder / CoT stripper |
| `coach_narrate` / `account_commentary` / `research_stream` | the three SSE endpoints |
| `_seed_chat_focus` | cross-seed chat focus from a skill turn |
| `_is_followup` / `_is_research_intent` | deterministic routing |
| `_build_research_bundle` / `_emit_bundle_sources` | research source ledger |
| `store.resolve_customer_detailed` / `resolve_customer_in_text` / `_key_in_text` | resolution + word-boundary matching |
| `coach.context.build_commentary_context` | grounding decision + near-match copy |
