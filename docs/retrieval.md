# Retrieval Reference — hybrid semantic search + knowledge graph

Senpai's retrieval has two layers beyond the original keyword/tag matching, both
**GPU-free and deterministic**, both degrading gracefully when optional deps/artifacts
are missing (the same "works offline, no model required" rule as the deal-health engine).

## 1. Hybrid semantic search

Searches by *meaning*, not just shared characters — a query for 『予算が理由で停滞』 also
finds 「コスト面で渋い」 notes.

**Architecture** (`senpai/retrieval/`):
- **`build_index.py`** — build step (run like `gen_seed.py`). Embeds each corpus with
  fastembed (ONNX/CPU, `config.EMBED_MODEL` = paraphrase-multilingual-MiniLM, 384-d) and
  **commits** the artifacts under `senpai/data/index/`, so runtime never needs a GPU or a
  model download for the corpus side — only the live query is embedded.
- **`semantic.py`** — runtime. Fuses two signals with **Reciprocal Rank Fusion**
  (`score = Σ 1/(k+rank)`, `k=config.RRF_K`):
  - **BM25** (lexical) over Janome-tokenized text (`rank_bm25`).
  - **Dense** cosine vs the committed vectors (query embedded on CPU).
  - Optional **cross-encoder rerank** behind `SENPAI_USE_RERANKER` (default off).

**Committed artifacts** (`senpai/data/index/`, regenerate with
`python -m senpai.retrieval.build_index`):
| File | What |
|---|---|
| `{corpus}.npy` | L2-normalized float32 embedding matrix (cosine = dot) |
| `{corpus}.meta.json` | per-row metadata + raw `text` + `snippet` (row-aligned to vectors) |
| `{corpus}.tokens.json` | precomputed BM25 tokens (so runtime never re-tokenizes the corpus) |
| `manifest.json` | model, dim, per-corpus count + content hash |

Corpora: **activities** (daily reports — the primary target) and **playbook**. Add more in
`build_index.CORPORA`.

**Graceful degrade** (mirrors `SENPAI_USE_LLM`): `dense + BM25 → BM25 → keyword`. Dense runs
only when `SENPAI_USE_EMBEDDINGS` (default on) AND fastembed is importable AND vectors exist;
otherwise BM25; if `rank_bm25`/Janome are absent, a pure substring layer still answers.
`semantic.mode()` reports the active layer.

**Fusion design (learned from stress testing — see `scripts/stress_retrieval.py`).** Three
choices make hybrid behave well on short, templated Japanese notes:
- **Text-space dedup.** The corpus has many duplicate reports; fusion ranks *distinct texts*
  (best occurrence per text) so duplicates can't flood a signal's candidate pool.
- **Zero-score filter + dense-weighted RRF** (`DENSE_WEIGHT=3` vs `BM25_WEIGHT=1`). A signal with
  no real match contributes nothing (no arbitrary noise), and the embedding model — the stronger
  signal for paraphrases — outweighs lexical BM25 while BM25 still helps exact-term queries.
- **Content-word tokenization** (`semantic._tokenize`). Janome POS tagging keeps only
  noun/verb/adjective/adverb base forms, dropping particles, light verbs (する/なる), suffixes
  (的/性) and lone hiragana — otherwise BM25 matches function words (e.g. 「判断**する**」 ≈
  「検討し**ます**」) and pollutes the ranking. Tokens are committed (`*.tokens.json`).

**API:** `semantic_search(query, corpus="activities", limit=5, tags=None) -> list[dict]`.

**Surfaced to the model:** the `search_notes` tool (semantic search over 日報), and
`retrieve_playbook` now ranks playbook entries via this layer internally (same signature/return,
keyword fallback) — so the junior/manager chats gain meaning-aware search with no caller changes.

## 2. Knowledge graph + multi-hop queries

Answers relational questions the flat layers can't (`senpai/graph/`):

- **`build.py`** — a `networkx.MultiDiGraph` built from the store at runtime (cached; rebuilt
  from the committed seed so it never drifts — no extra artifact). Nodes: `rep · customer · deal
  · product · industry:* · category:* · acttype:*`. Edges: `OWNS · FOR · CONCERNS · IN_CATEGORY
  · IN_INDUSTRY · HAD`. Deal nodes are denormalized (category/industry/outcome/rep/products/
  acttypes) so filters are a fast scan; the edges back path/neighborhood queries.
- **`query.py`** — parameterized (not free-form Cypher, so results are explainable):
  - `reps_who_win(category, industry, after_activity_type, min_deals)` → reps by win-rate on
    matching closed deals (the *"which reps win サーバー deals in 製造業 after a site survey"* query).
  - `account_graph(customer)` → an account's deals/reps/products neighborhood.
  - `connections(a, b)` → shortest relational path between two entities.
  - `similar_by_graph(deal_id)` → deals sharing rep/product/industry/category.

**Surfaced to the model:** the `query_graph` tool (`intent` = `reps_who_win | account |
connections | similar`), in `MANAGER_TOOLS` (+ junior account briefs).

## Config (`senpai/config.py`)
`INDEX_DIR` · `EMBED_MODEL` (env `SENPAI_EMBED_MODEL`) · `USE_EMBEDDINGS`
(`SENPAI_USE_EMBEDDINGS`, default on) · `USE_RERANKER` (`SENPAI_USE_RERANKER`, default off) ·
`RRF_K` (`SENPAI_RRF_K`, default 60).

## Tests
- `tests/conftest.py` forces **BM25-only** for the suite (hermetic, no model download). The
  dense path runs only with `SENPAI_TEST_DENSE=1`.
- `tests/test_semantic.py`, `tests/test_graph.py`.
- **Stress harness:** `scripts/stress_retrieval.py` — paraphrase recall, fusion sanity,
  determinism, score monotonicity, graceful degradation, edge-case/fuzz robustness, latency.
  Run: `SENPAI_TODAY=2026-06-16 PYTHONPATH=. .venv/bin/python scripts/stress_retrieval.py`.

## Phase 2b — GraphRAG community summaries (future, not built)
Microsoft-GraphRAG style: detect communities (networkx greedy-modularity / Louvain), generate an
LLM summary per cluster, and retrieve over those summaries for fuzzy *global* questions
("what themes are stalling our 製造業 deals?"). Deferred because it's LLM-dependent and heavier;
the deterministic KG above covers the structured multi-hop need today.

## Regenerate / verify
```bash
export SENPAI_TODAY=2026-06-16
python -m senpai.retrieval.build_index      # rewrite senpai/data/index/* (commit the result)
python -m senpai.graph.build                # print graph stats
python -m senpai.tools.impl                 # smoke every tool incl. search_notes / query_graph
SENPAI_TEST_DENSE=1 pytest -q               # full suite incl. the dense path
```
