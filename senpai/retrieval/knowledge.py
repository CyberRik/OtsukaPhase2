"""Keyword RAG over the validated knowledge corpus.

Spans three deterministic sources, all GPU-free keyword/tag scoring (the same
style as retrieval.playbook — no embeddings, no extra deps):
  * approved Principles      — the validated ground truth (knowledge.store)
  * approved GeneratedItems  — illustrative coaching scenarios that passed grounding
  * the senior-rep playbook  — tactical snippets (data.store)

Returns short, attributed/cited snippets the junior assistant can ground an
answer in. The model calls `search_knowledge()` like any other tool; results are
labelled by kind ([原則]/[事例]/[プレイブック]) and carry their provenance so the
assistant can cite who/what an answer rests on. Nothing here is generated — every
line traces back to a committed, human-approved record.
"""
from __future__ import annotations

from senpai.data import store as dstore
from senpai.knowledge import store as kstore
from senpai.retrieval.playbook import retrieve_playbook


def _tokens(text: str) -> list[str]:
    return [t for t in (text or "").replace("、", " ").replace("。", " ").split() if t]


def _score_principle(p, tags: list[str], q: str) -> int:
    """Tag overlap (+3) + tag-in-query (+2) + token substring hits (+1) — mirrors
    retrieval.playbook scoring so ranking is consistent across the corpus."""
    score = 0
    for t in tags:
        if any(t in pt or pt in t for pt in p.tags):
            score += 3
    for pt in p.tags:
        if q and pt in q:
            score += 2
    for tok in _tokens(q):
        if len(tok) >= 2 and tok in p.statement:
            score += 1
    return score


def search_knowledge(query: str = "", tags: list[str] | None = None,
                     limit: int = 4) -> list[tuple[int, str, str]]:
    """Rank the whole corpus against query/tags. Returns (score, kind, text)
    tuples, best first — the structured form the tool wrapper renders."""
    tags = [t.strip() for t in (tags or []) if t and t.strip()]
    q = (query or "").strip()
    results: list[tuple[int, str, str]] = []

    # 1. Approved principles — the validated ground truth, scored on relevance.
    for p in kstore.approved_principles():
        s = _score_principle(p, tags, q)
        if s:
            n = len(p.interview_ids)
            cites = "、".join(p.interview_ids) if p.interview_ids else "—"
            results.append((s + 2, "原則",
                            f"{p.statement}（根拠: 先輩{n}名 / {cites}）"))

    # 2. Approved + grounded coaching items (already relevance-filtered/sorted).
    for it in kstore.approved_items(tags=tags, query=q):
        conf = it.confidence(kstore.get_principle(it.provenance.principle_id))
        signal = "／".join(it.signals[:2]) if it.signals else "—"
        results.append((2, "事例", f"{it.scenario}（着眼点: {signal} / 確度{conf}）"))

    # 3. Senior-rep playbook tactical snippets.
    for e in retrieve_playbook(query=q, tags=tags):
        entry_id = e.get("entry_id", "Unknown")
        results.append((1, "プレイブック", f"{e['text']}（出典: Playbook {entry_id}）"))

    results.sort(key=lambda r: r[0], reverse=True)
    return results[:limit]
