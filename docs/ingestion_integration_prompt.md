# Integration Brief — wire the multimodal ingestion into the Senpai pipeline

> **How to use this file:** paste the whole thing to Claude Code as the task, then add your
> specifics in the **§7 "FILL THIS IN"** block at the bottom (where/how you want ingestion
> surfaced). Everything above §7 is durable context so a cold-start agent gets it right.

---

## 1. Mission

Take the **standalone multimodal ingestion prototype** (`senpai/ingestion/`) and integrate it
properly into the main Senpai pipeline so a rep can turn a **voice note / photo / text** into a
real `sales_activities` record that the deal-health engine and retrieval immediately see. Do it
in keeping with the repo's conventions (below) — not as a bolt-on.

## 2. Repo conventions you MUST honor (the DNA)

- **`data/store.py` is the single source of truth.** Everything (scoring, retrieval, tools,
  apps) reads through it. New data must enter through the store, not be sprinkled around.
- **Deterministic + GPU-free core.** Scoring/flags/retrieval are pure Python/CPU. The only
  things needing a network model are the LLM chat/narration and the *ingestion* multimodal
  calls — keep that boundary.
- **Optional-with-fallback.** Mirrors `SENPAI_USE_LLM` / `have_multimodal()`: if a key/model
  isn't present, degrade gracefully, never crash.
- **Committed artifacts.** Seed JSON (`data/seed/*.json`) and the retrieval index
  (`data/index/*`) are committed and byte-stable; regen scripts are `gen_seed.py` /
  `build_index.py`. If ingestion mutates activities, the retrieval index must be kept in sync.
- **The four SPR tables mirror `Schema.md` field-for-field.** A new `sales_activities` row must
  carry exactly the schema's fields (plus nothing that pollutes the table).
- **Tests must stay green** (currently `pytest -q` → ~76 passed, 1 skipped). Add tests for new
  behavior; keep them hermetic (no network/model download — mock the API).
- **Secrets:** `.env` and `senpai/.env` are gitignored. Never commit keys; never print secret
  values.

## 3. Current state of `senpai/ingestion/` (what exists today)

Two **overlapping** modules — consolidation is part of the job:

- **`multimodal.py`** — the good one. A CLI (`python -m senpai.ingestion.multimodal
  --audio|--image|--text`). Already wired to an **OpenAI-compatible multimodal endpoint** via
  config (works on **Groq's free tier**): `transcribe_audio` (Whisper), `extract_text_from_image`
  (vision/OCR), `extract_structured_activity` → `_structure_complete` (Groq, then local exp3, then
  a dict fallback). Output is a validated `ActivityExtraction` pydantic model. **It only prints
  JSON — it does NOT persist anything.**
- **`pipeline.py`** — older, **mock-only** multimodal (`process_audio`/`process_image` return
  hardcoded strings). Has `MultimodalIngestor.ingest_to_store(...)` which appends to the
  in-memory `store.all_activities()` list (NOT written to disk). **Bug:** `extract_activity`
  calls `simple_complete(...)` *outside* its try/except → crashes when the model server is down.
  Also can't run as a script (no `sys.path` shim).

**Config already added** (`senpai/config.py`): `INGEST_BASE_URL`, `INGEST_API_KEY`,
`INGEST_AUDIO_MODEL` (`whisper-large-v3`), `INGEST_VISION_MODEL` /
`INGEST_STRUCT_MODEL` (`meta-llama/llama-4-scout-17b-16e-instruct`), and `have_multimodal()`.
`_load_dotenv()` loads both repo-root `.env` and `senpai/.env`.

The target schema (`ActivityExtraction`) extracts: `activity_type` (one of the 9 literals),
`business_card_info`, `product_major_category`, `customer_challenge`, `daily_report`.

## 4. Required work (the integration itself)

1. **Consolidate to ONE module.** Keep `multimodal.py`'s real, robust implementation. Fold in
   anything worth keeping from `pipeline.py`, then **delete `pipeline.py`** and the duplicate
   `ActivityExtraction`. One `ActivityExtraction` schema, one ingestor.

2. **Add a real persistence path on the store.** `store.py` has NO write API today. Add e.g.
   `store.add_activity(record: dict) -> dict` that:
   - validates/fills the **full** `sales_activities` schema (see `Schema.md` §4 and the row built
     in `pipeline.py:ingest_to_store` as a reference shape),
   - **appends to `data/seed/sales_activities.json` on disk** (json, `ensure_ascii=False`,
     indent=2) and calls `store.reload()` so the in-memory cache reflects it,
   - is idempotent-friendly (assigns a new id / stable ordering).
   Then route ingestion through it. Decide with the user (see §7) whether writes go to the seed
   file or a separate `data/ingested/…` overlay that the store unions in (cleaner: keeps the
   synthetic seed pristine and the real-ingested data separate — recommended).

3. **Keep retrieval in sync.** New daily reports should become searchable. After a write, either
   call `senpai.retrieval.build_index.build()` (simplest) or add an incremental index-append.
   At minimum, document/trigger a reindex so `search_notes` sees ingested notes.

4. **Fix the field-correctness bugs** when building the activity record:
   - `fiscal_year`/`fiscal_quarter`: use the **Japanese FY** helper (April start) — reuse the
     logic in `senpai/data/gen_seed.py:_fy()` (don't use calendar quarters).
   - `sales_info`: resolve `department`/`division` from the rep via `store.get_rep(employee_id)`,
     don't hardcode.
   - Drop the bogus `opportunity_id` default (deals have none) — derive it sensibly or omit.
   - Populate `customer_id` / `deal_id` from the caller (see §7 for how they're supplied).
   - `activity_date` = today (`config.today()`), `closed_flag=False`, `quote_id`/`order_id=None`.

5. **Config/deps hygiene.** Add `pydantic` to `requirements.txt` (currently only transitive).
   Keep model ids in config/env (already done) so Groq id rotations don't need code edits.

6. **Tests** (`tests/test_ingestion.py`, hermetic): mock `multimodal_client` /
   `simple_complete` so no network; assert (a) extraction maps to the schema, (b) the dict
   fallback path on parse failure, (c) `store.add_activity` writes a schema-complete row and the
   store/scoring see it, (d) `have_multimodal()` gating. Keep the suite green.

## 5. Files & helpers to reuse (don't reinvent)

- `senpai/ingestion/multimodal.py` — base implementation (transcribe/vision/structure).
- `senpai/config.py` — `INGEST_*`, `have_multimodal()`, `today()`, `_fy`-style FY logic lives in `gen_seed.py`.
- `senpai/data/store.py` — `_load()`/`reload()` cache pattern, `get_deal`, `get_rep`,
  `get_customer`, `all_activities`; **add the write API here**.
- `senpai/data/gen_seed.py:_fy(d_iso)` — Japanese fiscal year/quarter.
- `senpai/retrieval/build_index.py:build()` — rebuild the semantic index after a write.
- `Schema.md` §4 — the authoritative `sales_activities` field list.
- Tool pattern: `senpai/tools/impl.py` (+ `schemas.py`, role sets) if ingestion is exposed as a
  model-callable tool. Streamlit app pattern: `senpai/apps/*.py`. Gradio chat: `apps/junior_chat.py`.

## 6. Acceptance criteria

- One ingestion module; `pipeline.py` removed; no duplicate schema.
- `python -m senpai.ingestion.<module> --text/--image/--audio …` produces a **persisted**
  `sales_activities` row (schema-complete, correct JA fiscal quarter, rep-resolved `sales_info`).
- After ingestion, the new note is visible to `store.activities_for_deal(...)`, the deal-health
  engine, and `search_notes` (index refreshed).
- Graceful fallback with no key/model (no crash).
- `pydantic` in `requirements.txt`; `tests/test_ingestion.py` added; `pytest -q` green.
- No secrets committed; determinism of seed/index preserved (or a clean separate overlay).

## 7. FILL THIS IN — your specifics (the user completes this before running)

> Tell the agent **where/how** you want ingestion surfaced and how the activity is attributed.
> Examples to pick from / edit:

- **Surface:** ⟨ CLI only / a model-callable `ingest_activity` tool in junior chat / a Streamlit
  "Upload" page (`apps/…`) / an API endpoint in `api/server.py` / the Next.js web app ⟩
- **Attribution:** how are `customer_id`, `deal_id`, `employee_id` provided? ⟨ CLI args / resolved
  from the transcript via `store.resolve_customer` + deal pick / chosen in a UI dropdown ⟩
- **Persistence target:** ⟨ append to `data/seed/sales_activities.json` / separate
  `data/ingested/…` overlay unioned by the store (recommended) ⟩
- **Reindex:** ⟨ rebuild index automatically after each write / a manual `build_index` step ⟩
- **Provider:** keep **Groq free tier** (default) or switch (`INGEST_*` env). Audio model
  `whisper-large-v3`; vision/struct `meta-llama/llama-4-scout-17b-16e-instruct`.
- **Anything else:** ⟨ confirmation/preview-before-save? human edit step? batch folder ingest? ⟩

When this block is filled, implement §4 honoring §2, verify against §6, and report what changed.
