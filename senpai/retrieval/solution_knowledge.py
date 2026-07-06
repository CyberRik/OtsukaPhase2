"""Solution knowledge — search over Otsuka Shokai's real product/solution pages.

Generic, capability-agnostic retrieval: given a free-text query (and optional
filters), returns ranked solution records describing what Otsuka actually sells
that addresses it — named products/services (m-FILTER, CarriRo, ARCHITREND ZERO,
UTM/firewall lines, ...), not internal rule-engine category labels. No coupling to
deal/customer objects or any particular caller (Opportunity Intelligence is one
consumer, not the only one) — this module is a peer of retrieval.knowledge, not a
subordinate of it.

Backed by the `otsuka_kb` corpus (senpai/retrieval/build_index.py), scoped here to
`/products/*` pages and excluding `/products/case/*`: that sub-path is a thin,
repeated carousel of ~2 companies, not a real case-study database (see
docs/otsuka-knowledge-integration.md) — the deep, distinct content is the ~3,500
solution/product description pages across ~100 categories.
"""
from __future__ import annotations

import re
from typing import Any

from senpai.retrieval.semantic import lexical_support_urls, semantic_search

_CORPUS = "otsuka_kb"
_PRODUCTS_PREFIX = "/products/"
_CASE_PREFIX = "/products/case/"

# Category taxonomy comes free from the URL path — reliable, zero-NLP, and
# already a meaningful ~100-way breakdown (security/mail, cad/kss, ai-iot/robot, ...).
_CATEGORY_RE = re.compile(r"/products/([^/?]+(?:/[^/?]+)?)")
_TITLE_RE = re.compile(r"^#+\s*(.+)$", re.MULTILINE)


def _category(url: str) -> str:
    m = _CATEGORY_RE.search(url)
    return m.group(1) if m else ""


def _title(text: str, url: str) -> str:
    """First markdown heading on the page, falling back to the URL's last path
    segment when the page has none — never fabricated."""
    m = _TITLE_RE.search(text or "")
    if m:
        return m.group(1).strip()
    seg = url.rstrip("/").rsplit("/", 1)[-1]
    return seg or url


def search_solution_knowledge(query: str, filters: dict[str, Any] | None = None,
                              limit: int = 4) -> list[dict]:
    """Search Otsuka Shokai's real product/solution pages for `query`.

    Returns a list of `{"solution": {name, category, summary, source, relevance}}`,
    ranked best-first — reusable metadata shape, not specific to any one caller.

    `filters` (optional): `{"category": "security"}` restricts to pages whose
    derived category contains the given substring (case-insensitive).
    """
    filters = filters or {}
    category_filter = str(filters.get("category") or "").strip().lower()

    # Fetch a larger pool than `limit` since case/non-product pages, the lexical
    # floor, and a category filter are all applied *after* the corpus search —
    # semantic_search has no notion of URL-based filtering itself.
    pool_limit = max(limit * 5, 20)
    hits = semantic_search(query, corpus=_CORPUS, limit=pool_limit)

    # Dense cosine similarity on this embedding model is anisotropic — it never
    # cleanly hits zero, even for unrelated text (a nonsense query still "matches"
    # something at ~0.5 cosine). BM25 has a true zero, so require at least one
    # literal query token to appear in the hit *before* trusting the dense rank —
    # this is what rejects abstract one-word queries drifting onto an unrelated
    # page. `None` means BM25 is unavailable; skip the floor and degrade to
    # dense/keyword ranking only, same as the rest of this module.
    supported = lexical_support_urls(query, _CORPUS)

    out: list[dict] = []
    for hit in hits:
        url = hit.get("url", "")
        if not url or _PRODUCTS_PREFIX not in url or _CASE_PREFIX in url:
            continue
        if supported is not None and url not in supported:
            continue
        category = _category(url)
        if category_filter and category_filter not in category.lower():
            continue
        text = hit.get("text", "")
        name = _title(text, url)
        summary = (hit.get("snippet") or text[:200]).strip()
        # The snippet is just the page's leading characters, so it usually starts
        # with the same heading already used as `name` — drop that duplication.
        leading_heading = re.match(r"^#+\s*.+", summary)
        if leading_heading:
            summary = summary[leading_heading.end():].strip()
        if not summary:
            summary = name

        out.append({
            "solution": {
                "name": name,
                "category": category,
                "summary": summary,
                "source": url,
                "relevance": hit.get("score", 0.0),
            }
        })
        if len(out) >= limit:
            break
    return out
