"""Hybrid semantic search — BM25 + dense embeddings, fused with Reciprocal Rank
Fusion (RRF). GPU-free at runtime: the corpus vectors are committed by
build_index.py, so only the live query is embedded (one short CPU call).

Layered, with graceful degrade (mirrors the SENPAI_USE_LLM optional pattern):
    dense + BM25  →  BM25 only  →  keyword substring
The richest layer whose dependencies/artifacts are present wins, so the app and
the tests always return *something* offline with no model download.

Public API:
    semantic_search(query, corpus="activities", limit=5, tags=None) -> list[dict]
Each hit is the row's metadata (deal_id/customer_id/…, snippet, text) + `score`.
"""
from __future__ import annotations

import importlib.util
import json
from functools import lru_cache

import numpy as np

from senpai import config


# --- optional dependencies (all degrade cleanly) ---------------------------
def _has(module: str) -> bool:
    # find_spec checks availability WITHOUT importing — so merely importing this
    # module never pulls in heavy onnxruntime/fastembed (only the dense path does).
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


HAS_BM25 = _has("rank_bm25")
HAS_JANOME = _has("janome")
HAS_FASTEMBED = _has("fastembed")


def reload() -> None:
    """Drop cached vectors / BM25 / tokenizer / model (tests, post-rebuild)."""
    for fn in (_load_vectors, _load_meta, _load_tokens, _tokenizer, _bm25_for, _embed_model):
        fn.cache_clear()


# --- committed dense index --------------------------------------------------
@lru_cache(maxsize=None)
def _load_vectors(corpus: str):
    path = config.INDEX_DIR / f"{corpus}.npy"
    return np.load(path) if path.exists() else None


@lru_cache(maxsize=None)
def _load_meta(corpus: str) -> tuple[dict, ...]:
    path = config.INDEX_DIR / f"{corpus}.meta.json"
    if not path.exists():
        return ()
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def available_corpora() -> list[str]:
    if not config.INDEX_DIR.exists():
        return []
    return sorted(p.name[:-len(".meta.json")] for p in config.INDEX_DIR.glob("*.meta.json"))


# --- Japanese tokenization + BM25 ------------------------------------------
@lru_cache(maxsize=1)
def _tokenizer():
    from janome.tokenizer import Tokenizer
    return Tokenizer()


# Content-word POS only — dropping particles/auxiliaries/symbols (の, か, ない, 。…)
# is what keeps BM25 from matching on semantically-empty function words, which
# otherwise inject noise that drowns the dense signal during fusion.
_KEEP_POS = ("名詞", "動詞", "形容詞", "副詞")
# Noun/verb *subtypes* that carry no topic signal: 接尾 (suffixes like 的/性),
# 非自立 (dependent forms), 代名詞 (誰/それ), 数 (bare numbers).
_DROP_SUBPOS = ("接尾", "非自立", "代名詞", "数")
# Generic light verbs / formal nouns that survive POS tagging but carry no topic
# signal (e.g. 「判断する」 and 「検討します」 both reduce to する → spurious BM25 match).
_STOPWORDS = {"する", "なる", "ある", "いる", "できる", "れる", "られる", "おる", "いう",
              "こと", "もの", "ため", "よう", "とき", "ところ", "それ", "これ", "あれ"}


def _is_hiragana1(t: str) -> bool:
    return len(t) == 1 and "぀" <= t <= "ゟ"   # lone hiragana = function word


def _tokenize(text: str) -> list[str]:
    """Content-word tokens (base form), via Janome POS tagging, minus generic
    light-verb / lone-hiragana stopwords. Falls back to a whitespace split when
    Janome is unavailable."""
    text = (text or "").strip()
    if not text:
        return []
    if HAS_JANOME:
        toks = []
        for tok in _tokenizer().tokenize(text):
            parts = tok.part_of_speech.split(",")
            if parts[0] not in _KEEP_POS or (len(parts) > 1 and parts[1] in _DROP_SUBPOS):
                continue
            base = tok.base_form
            base = base if base and base != "*" else tok.surface
            if base in _STOPWORDS or _is_hiragana1(base):
                continue
            toks.append(base)
        return toks
    return text.replace("、", " ").replace("。", " ").split()


@lru_cache(maxsize=None)
def _load_tokens(corpus: str) -> tuple[list[str], ...] | None:
    """Committed BM25 tokens for a corpus (built by build_index), so runtime doesn't
    re-tokenize the whole corpus. None when the file is absent."""
    path = config.INDEX_DIR / f"{corpus}.tokens.json"
    if not path.exists():
        return None
    return tuple(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=None)
def _bm25_for(corpus: str):
    """(BM25Okapi, tokenized_corpus) for a corpus, or None when unavailable.
    Uses committed tokens when present (fast); else tokenizes the corpus text."""
    if not HAS_BM25:
        return None
    meta = _load_meta(corpus)
    if not meta:
        return None
    from rank_bm25 import BM25Okapi
    tokenized = _load_tokens(corpus)
    tokenized = list(tokenized) if tokenized is not None else [_tokenize(m.get("text", "")) for m in meta]
    return BM25Okapi(tokenized), tokenized


# --- dense query embedding (the only runtime model call) -------------------
@lru_cache(maxsize=1)
def _embed_model():
    from fastembed import TextEmbedding
    return TextEmbedding(config.EMBED_MODEL, threads=1)


def _dense_query_vector(query: str):
    from senpai.retrieval.build_index import query_text
    model = _embed_model()
    vec = np.asarray(list(model.embed([query_text(query)]))[0], dtype=np.float32)
    n = np.linalg.norm(vec)
    return vec / n if n else vec


def _use_dense(corpus: str) -> bool:
    return (config.USE_EMBEDDINGS and HAS_FASTEMBED
            and _load_vectors(corpus) is not None)


# --- fusion -----------------------------------------------------------------
# Fusion works in *text space*, not row space: the corpus has many duplicate
# templated reports, so we collapse each signal to its best-scoring occurrence per
# distinct text before ranking. This stops duplicates from flooding a signal's
# candidate pool (which otherwise lets a mediocre note that appears in both BM25 and
# dense lists outrank an excellent dense-only match), and yields diverse results.
def _ranks_by_text(scores: np.ndarray, meta: tuple[dict, ...], pool: int,
                   min_score: float = 0.0) -> tuple[dict[str, int], dict[str, int]]:
    """Rank *distinct texts* by their best row score (desc), keeping only texts
    whose best score exceeds `min_score`. Returns ({text: 1-based rank},
    {text: representative row index}). Dropping non-positive scores is what stops a
    signal with *no real match* (e.g. BM25 on a purely-semantic query) from injecting
    arbitrarily-ranked noise into the fusion."""
    best_idx: dict[str, int] = {}
    best_score: dict[str, float] = {}
    for i, sc in enumerate(scores):
        t = meta[i].get("text", "")
        if t not in best_score or sc > best_score[t]:
            best_score[t] = float(sc)
            best_idx[t] = i
    order = sorted((t for t in best_score if best_score[t] > min_score),
                   key=lambda t: best_score[t], reverse=True)[:pool]
    return {t: r for r, t in enumerate(order, start=1)}, best_idx


def _keyword_scores(query: str, meta: tuple[dict, ...]) -> np.ndarray:
    """Last-resort lexical scoring (substring token hits) — no deps at all."""
    toks = [t for t in _tokenize(query) if len(t) >= 2]
    out = np.zeros(len(meta), dtype=np.float32)
    for i, m in enumerate(meta):
        text = m.get("text", "")
        out[i] = sum(1 for t in toks if t in text)
    return out


def _maybe_rerank(query: str, hits: list[dict], limit: int) -> list[dict]:
    """Optional cross-encoder rerank (off unless SENPAI_USE_RERANKER). Best-effort:
    any failure leaves the RRF order untouched."""
    if not config.USE_RERANKER or not hits or not HAS_FASTEMBED:
        return hits[:limit]
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        ce = _cross_encoder()
        scores = list(ce.rerank(query, [h["text"] for h in hits]))
        for h, s in zip(hits, scores):
            h["rerank_score"] = float(s)
        hits.sort(key=lambda h: h["rerank_score"], reverse=True)
    except Exception:  # noqa: BLE001 — reranker is a nice-to-have, never required
        pass
    return hits[:limit]


@lru_cache(maxsize=1)
def _cross_encoder():
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    return TextCrossEncoder("Xenova/ms-marco-MiniLM-L-6-v2")


# --- public API -------------------------------------------------------------
def semantic_search(query: str, corpus: str = "activities", limit: int = 5,
                    tags: list[str] | None = None, pool: int = 50) -> list[dict]:
    """Hybrid (BM25 + dense, RRF-fused) search over a committed corpus. Falls back
    to BM25, then keyword, depending on what's installed. `tags` are folded into
    the query and give a small exact-match boost (used by playbook retrieval)."""
    meta = _load_meta(corpus)
    if not meta:
        return []
    tags = [t for t in (tags or []) if t]
    effective = " ".join([query or "", *tags]).strip()
    if not effective:
        return []

    # Each signal contributes a (ranks_by_text, weight) plus a text→representative
    # row map; RRF fuses per distinct text. Dense is weighted higher (config).
    signals: list[tuple[dict[str, int], float]] = []
    rep: dict[str, int] = {}                         # text → representative row index

    bm = _bm25_for(corpus)
    if bm is not None:
        bm25, _ = bm
        ranks, idx = _ranks_by_text(np.asarray(bm25.get_scores(_tokenize(effective))), meta, pool)
        signals.append((ranks, config.BM25_WEIGHT))
        rep.update(idx)

    if _use_dense(corpus):
        sims = _load_vectors(corpus) @ _dense_query_vector(effective)
        ranks, idx = _ranks_by_text(sims, meta, pool)
        signals.append((ranks, config.DENSE_WEIGHT))
        rep.update(idx)                              # dense representative preferred

    if signals:
        fused: dict[str, float] = {}
        for ranks, weight in signals:
            for text, r in ranks.items():
                fused[text] = fused.get(text, 0.0) + weight / (config.RRF_K + r)
    else:  # no BM25, no dense → pure keyword fallback (still deduped by text)
        kw = _keyword_scores(effective, meta)
        ranks, idx = _ranks_by_text(kw, meta, pool)
        rep.update(idx)
        fused = {t: 1.0 / (config.RRF_K + r) for t, r in ranks.items() if kw[idx[t]] > 0}

    if not fused:
        return []

    # Small boost when the representative row's situation_tags overlap the request.
    if tags:
        tagset = set(tags)
        for text in list(fused):
            if tagset & set(meta[rep[text]].get("situation_tags", [])):
                fused[text] += 0.01

    n = max(limit, pool) if config.USE_RERANKER else limit
    ranked = sorted(fused, key=lambda t: fused[t], reverse=True)[:n]
    hits = [{**meta[rep[t]], "score": round(fused[t], 6)} for t in ranked]
    return _maybe_rerank(effective, hits, limit)


def mode() -> str:
    """Which retrieval layer is active — for diagnostics/UI badges."""
    if config.USE_EMBEDDINGS and HAS_FASTEMBED and available_corpora():
        return "hybrid (BM25 + dense)"
    if HAS_BM25:
        return "BM25"
    return "keyword"
