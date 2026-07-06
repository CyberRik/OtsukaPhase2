# Otsuka Knowledge Integration — grounding the coach in real company facts

Companion to [`retrieval.md`](retrieval.md) — this doc covers one specific corpus (`otsuka_kb`)
added to that hybrid semantic-search system, and the workflow used to build its index on a
remote GPU box instead of locally.

## The source data

Reps and the coach previously had no way to ground an answer in Otsuka Shokai's own public
facts (IR figures, product/solution pages, compliance policy) — the model would have to guess
or hallucinate. `data/otsuka_*.jsonl` at the repo root is a 4-stage crawl→clean pipeline that
made this groundable, staged **before** this integration but never wired to a consumer:

| Stage | File | What |
|---|---|---|
| 1 | `otsuka_1_raw.jsonl` | Raw crawled pages from otsuka-shokai.co.jp (10,843 pages) |
| 2 | `otsuka_2_processed_llm.jsonl` | + metadata (url/title/links) + an LLM-cleaned pass |
| 3 | `otsuka_3_pretrain_format.jsonl` | Stripped to `{"text"}`; some rows flagged "no substantial info" |
| 4 | `otsuka_4_pretrain_cleaned.jsonl` | Filtered to the good subset (9,826 rows), each with a `quality_evaluation` (score + reasoning) and its source `url` |

**Not integrated**: `data/otsuka_sales_dpo_train.jsonl` (270 preference pairs for a
"veteran salesperson" persona) has no consumer in this repo — it's fine-tuning/DPO alignment
data, not a retrieval corpus. Today's coach persona is prompt-only (`senpai/llm/synth_style.py`).
Using the DPO set means fine-tuning the served model outside this repo and pointing the endpoint
at the resulting checkpoint — a model-training project, not a retrieval integration.

## Integration into the existing hybrid-search system

`otsuka_kb` is just a new corpus in `senpai/retrieval/build_index.py`'s existing registry — no
new subsystem, no new capability/tool signature.

- `build_index._corpus_otsuka_kb()` reads `data/otsuka_4_pretrain_cleaned.jsonl` (repo-root
  `data/`, distinct from the package's own `senpai/data/`) and emits `{"text", "url",
  "quality_score"}` docs — no new cleaning, stage 4 is already the validated subset.
  `python -m senpai.retrieval.build_index` embeds and commits it exactly like any other corpus
  (see `retrieval.md` for the embedding/BM25/RRF-fusion mechanics that already existed).
- `senpai/retrieval/knowledge.py`'s `search_knowledge()` — already the function backing the
  planner's `knowledge` capability (`senpai/planner/capabilities.py`) and the `search_knowledge`
  tool (`senpai/tools/impl.py`) — now adds a 4th source alongside approved principles / coaching
  items / playbook: `semantic_search(query, corpus="otsuka_kb", limit=2)`, labelled `[公式]`
  and cited with the source URL. Company facts just show up as another cited line wherever
  `search_knowledge` already ran.
- Degrades the same way as every other corpus: if the index files are missing (e.g. a fresh
  checkout before running `build_index`), `semantic_search` returns `[]` for `otsuka_kb` and
  `search_knowledge` behaves exactly as it did before this change.

**Verified end-to-end** via `search_knowledge(query="大塚商会 資本金 設立")` — returns real
`[公式]`-labelled hits with genuine `otsuka-shokai.co.jp` URLs (e.g. a human-capital-management
column and a 2023 press release about the Happiness Planet partnership), alongside the existing
`[プレイブック]` hits. `tests/test_semantic.py` still passes unchanged.

## Building the index on a remote GPU box

`build_index.py` pins `OMP_NUM_THREADS=1` for reproducible embeddings, so a big corpus (e.g.
`otsuka_kb`'s 9,826 full-page docs) is single-core-bound regardless of whether the machine has a
GPU — fastembed's ONNX export of `paraphrase-multilingual-MiniLM-L12-v2` runs on CPU either way;
there's no CUDA execution provider wired up for it. What actually helped when the local Windows
box was still grinding after 25+ minutes was moving the job to a *faster/idle* CPU — the shared
box at `100.101.186.29` (20-core aarch64, GB10) that already serves `atlas-35b` for inference —
which finished the same corpus in ~13 minutes. This is a one-off manual workflow, not a script:

1. **Package + ship** just what the build needs (not the whole repo — no `.venv`, `node_modules`,
   `senpai/data/index`, or unrelated large root files):
   ```bash
   tar --exclude='senpai/data/index' --exclude='__pycache__' -czf /tmp/senpai_pkg.tar.gz senpai/
   scp /tmp/senpai_pkg.tar.gz team-a@100.101.186.29:~/senpai-build/
   scp data/otsuka_4_pretrain_cleaned.jsonl team-a@100.101.186.29:~/senpai-build/data/
   ```
2. **Match dependency versions exactly** (`pip show fastembed onnxruntime rank_bm25 janome numpy`
   locally, then install the same pins in a fresh venv on the remote box) — the corpus vectors
   only need to be self-consistent with the query embedder wherever the app actually runs, but
   pinning versions removes any doubt rather than relying on "probably fine."
3. **Build only the new corpus** — don't let a from-scratch `build()` re-embed corpora that
   already built fine locally; override the registry for that one call:
   ```python
   from senpai.retrieval import build_index as bi
   bi.CORPORA = {"otsuka_kb": bi._corpus_otsuka_kb}
   bi.build()
   ```
4. **Copy back only the new corpus's three files** (`{corpus}.npy/.meta.json/.tokens.json`) —
   `build()` always rewrites `manifest.json` from whatever's in `CORPORA` at call time, so the
   remote manifest.json contains *only* the corpus you built there. Never scp that over the local
   one; instead read the remote manifest's entry for the new corpus and merge it by hand into the
   local `manifest.json`'s `corpora` dict, keeping the existing entries untouched.
5. Smoke-test locally afterward (`search_knowledge`/`semantic_search` against the new corpus) —
   the remote build never touched anything the local app serves from until you copy the files back.

Nothing in the running app needs to know a corpus was built elsewhere; `semantic.py` just reads
whatever `.npy`/`.meta.json`/`.tokens.json` files exist under `INDEX_DIR`.

Leftover scratch state from this build sits in `~/senpai-build/` in team-a's home dir on the
remote box (package copy + venv, ~130MB) — harmless, not cleaned up automatically.
