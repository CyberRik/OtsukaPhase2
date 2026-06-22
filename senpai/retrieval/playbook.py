"""Retrieval over the playbook and similar deals.

Playbook retrieval is **hybrid semantic** (BM25 + dense embeddings, fused) when the
committed index is present (senpai/retrieval/semantic.py), and falls back to the
original keyword/tag scoring below when it isn't — so callers always get results
offline. `find_similar_deals` stays a deterministic feature-match. All GPU-free.
"""
from __future__ import annotations

from senpai.data import store


def _tokens(text: str) -> list[str]:
    return [t for t in (text or "").replace("、", " ").replace("。", " ").split() if t]


def _retrieve_playbook_keyword(query: str, tags: list[str], limit: int) -> list[dict]:
    """Original deterministic tag-overlap + substring scoring (the fallback)."""
    q = (query or "").strip()
    scored = []
    for entry in store.all_playbook():
        score = 0
        etags = entry.get("situation_tags", [])
        for t in tags:
            if any(t in et or et in t for et in etags):
                score += 3
        for et in etags:
            if q and et in q:
                score += 2
        for tok in _tokens(q):
            if len(tok) >= 2 and tok in entry.get("text", ""):
                score += 1
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


def retrieve_playbook(query: str = "", tags: list[str] | None = None,
                      limit: int = 3) -> list[dict]:
    """Rank playbook entries by relevance to a situation. Uses hybrid semantic
    search when the index is available, else keyword/tag scoring. Returns the top
    `limit` entries as raw playbook dicts (unchanged shape for all callers)."""
    tags = [t.strip() for t in (tags or []) if t.strip()]
    q = (query or "").strip()
    if q or tags:
        try:
            from senpai.retrieval import semantic
            hits = semantic.semantic_search(q, corpus="playbook", limit=limit, tags=tags)
            if hits:
                by_id = {e["entry_id"]: e for e in store.all_playbook()}
                out = [by_id[h["entry_id"]] for h in hits if h.get("entry_id") in by_id]
                if out:
                    return out[:limit]
        except Exception:  # noqa: BLE001 — any index/dep issue → keyword fallback
            pass
    return _retrieve_playbook_keyword(q, tags, limit)


def find_similar_deals(customer_id: str = "", industry: str = "",
                       profile_tags: list[str] | None = None,
                       limit: int = 3) -> list[dict]:
    """Feature-match deals on the customer's industry / size / profile tags —
    useful for new or thin customers with little history of their own."""
    target = store.get_customer(customer_id) if customer_id else None
    if target:
        industry = industry or target.get("industry", "")
        profile_tags = profile_tags or target.get("profile_tags", [])
    profile_tags = profile_tags or []

    scored = []
    for deal in store.all_deals():
        if customer_id and deal["customer_id"] == customer_id:
            continue
        cust = store.get_customer(deal["customer_id"])
        if not cust:
            continue
        score = 0
        if industry and cust.get("industry") == industry:
            score += 3
        score += len(set(profile_tags) & set(cust.get("profile_tags", [])))
        if target and cust.get("size") == target.get("size"):
            score += 1
        if score:
            scored.append((score, deal))
    scored.sort(key=lambda x: (x[0], x[1]["deal_id"]), reverse=True)
    return [d for _, d in scored[:limit]]
