"""Build the committed dense-embedding index for hybrid semantic search.

Run `python -m senpai.retrieval.build_index` to (re)write senpai/data/index/*.
Like gen_seed.py, the output is a committed build artifact so the *runtime* never
needs a GPU or a model download for the corpus side — only the live query is
embedded at query time (see senpai/retrieval/semantic.py).

For each corpus we write three files under INDEX_DIR:
    {corpus}.npy        float32 (N, dim) — L2-normalized row vectors (cosine = dot)
    {corpus}.meta.json  list of per-row metadata, including the raw `text` (so BM25
                        and snippets stay row-aligned with the vectors, no drift)
    manifest.json       {model, dim, corpora: {name: {count, sha256-of-text}}}

Embeddings come from fastembed (ONNX, CPU). onnxruntime is pinned to 1 thread for
reproducibility. The model is config.EMBED_MODEL (a multilingual sentence model);
e5-family models get the required "passage:"/"query:" prefixes, others don't.
"""
from __future__ import annotations

import hashlib
import json
import os

# Pin threads BEFORE onnxruntime is imported (via fastembed) for reproducibility.
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np

from senpai import config
from senpai.data import store

# Number of leading characters kept as a display snippet in the meta.
_SNIPPET = 120


def _is_e5(model: str) -> bool:
    return "e5" in model.lower()


def passage_text(text: str, model: str | None = None) -> str:
    """Doc-side text, with the e5 'passage:' prefix when the model needs it."""
    model = model or config.EMBED_MODEL
    return f"passage: {text}" if _is_e5(model) else text


def query_text(text: str, model: str | None = None) -> str:
    """Query-side text, with the e5 'query:' prefix when the model needs it."""
    model = model or config.EMBED_MODEL
    return f"query: {text}" if _is_e5(model) else text


# ---------------------------------------------------------------------------
# Corpora — each returns a list of {"text": <to embed/tokenize>, ...metadata}.
# ---------------------------------------------------------------------------

def _corpus_activities() -> list[dict]:
    """Daily reports — the primary semantic-search target."""
    docs = []
    for a in store.all_activities():
        report = (a.get("daily_report") or "").strip()
        if not report:
            continue
        challenge = (a.get("customer_challenge") or "").strip()
        text = f"{report} {challenge}".strip()
        docs.append({
            "text": text,
            "deal_id": a.get("deal_id"),
            "customer_id": a.get("customer_id"),
            "activity_date": a.get("activity_date"),
            "activity_type": a.get("activity_type"),
        })
    return docs


def _corpus_playbook() -> list[dict]:
    """Senior reps' tactical advice (text + situation tags)."""
    docs = []
    for e in store.all_playbook():
        tags = e.get("situation_tags", [])
        text = f"{e.get('text', '')} {' '.join(tags)}".strip()
        docs.append({
            "text": text,
            "entry_id": e.get("entry_id"),
            "situation_tags": tags,
            "author_rep_id": e.get("author_rep_id"),
            "source_deal_id": e.get("source_deal_id"),
        })
    return docs


# Repo-root data/ (outside the package) — company-facts corpora staged there,
# distinct from PKG_DIR/data (seed/index/generated build artifacts).
_REPO_DATA_DIR = config.PKG_DIR.parent / "data"


def _corpus_otsuka_kb() -> list[dict]:
    """Otsuka Shokai public-website facts (company/product/IR pages), pre-filtered
    for quality by an LLM pass. See data/otsuka_4_pretrain_cleaned.jsonl — each row
    already carries a quality_evaluation.score and its source url."""
    path = _REPO_DATA_DIR / "otsuka_4_pretrain_cleaned.jsonl"
    if not path.exists():
        return []
    docs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = (row.get("text") or "").strip()
            if not text:
                continue
            docs.append({
                "text": text,
                "url": row.get("url", ""),
                "quality_score": (row.get("quality_evaluation") or {}).get("score"),
            })
    return docs


# Registry: corpus name -> builder. semantic.py loads whatever exists here.
CORPORA = {
    "activities": _corpus_activities,
    "playbook": _corpus_playbook,
    "otsuka_kb": _corpus_otsuka_kb,
}


def _embed(texts: list[str], model_name: str):
    """L2-normalized float32 embeddings for `texts` (rows aligned to input)."""
    from fastembed import TextEmbedding
    model = TextEmbedding(model_name, threads=1)
    prefixed = [passage_text(t, model_name) for t in texts]
    vecs = np.asarray(list(model.embed(prefixed)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def _hash_texts(texts: list[str]) -> str:
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def build() -> dict:
    store.reload()
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    model_name = config.EMBED_MODEL
    manifest = {"model": model_name, "dim": None, "corpora": {}}

    # Deferred import (avoids a circular import at module load) — reuse the exact
    # runtime tokenizer so committed BM25 tokens match query-time tokenization.
    from senpai.retrieval.semantic import _tokenize

    for name, builder in CORPORA.items():
        docs = builder()
        texts = [d["text"] for d in docs]
        vecs = _embed(texts, model_name)
        np.save(config.INDEX_DIR / f"{name}.npy", vecs)
        meta = [{**d, "snippet": d["text"][:_SNIPPET]} for d in docs]
        (config.INDEX_DIR / f"{name}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Precompute BM25 tokens so runtime never re-tokenizes the whole corpus.
        tokens = [_tokenize(t) for t in texts]
        (config.INDEX_DIR / f"{name}.tokens.json").write_text(
            json.dumps(tokens, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest["dim"] = int(vecs.shape[1])
        manifest["corpora"][name] = {"count": len(docs), "hash": _hash_texts(texts)}
        print(f"wrote index/{name}.npy ({vecs.shape[0]}×{vecs.shape[1]}) + meta + tokens")

    (config.INDEX_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote index/manifest.json (model={model_name}, dim={manifest['dim']})")
    return manifest


if __name__ == "__main__":
    build()
