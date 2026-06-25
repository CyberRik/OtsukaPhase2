"""Persistence + queries for the knowledge pipeline.

Two committed JSON files under knowledge/seed/ (sources, principles) plus a
generated/ file for Layer-2 items. Writable (the review UI updates item status),
so unlike senpai.data.store this is not lru_cached — it reloads on demand.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from senpai.knowledge.schema import (
    STATUS_APPROVED, GeneratedItem, Principle, Source,
)

KDIR = Path(__file__).resolve().parent
SEED_DIR = KDIR / "seed"
SOURCES_F = SEED_DIR / "sources.json"
PRINCIPLES_F = SEED_DIR / "principles.json"
ITEMS_F = SEED_DIR / "generated_items.json"
# Sidecar overlays for manager-contributed knowledge (gitignored). Kept separate
# from the committed seed so it stays canonical/byte-stable — the manager's tacit
# knowledge is appended here and read as an overlay, mirroring senpai.data.store.
SOURCES_INGESTED_F = SEED_DIR / "sources.ingested.json"
PRINCIPLES_INGESTED_F = SEED_DIR / "principles.ingested.json"


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


# --- sources / principles (seed + ingested overlay) ------------------------
def all_sources() -> list[Source]:
    return [Source(**d) for d in _read(SOURCES_F) + _read(SOURCES_INGESTED_F)]


def all_principles() -> list[Principle]:
    return [Principle.from_dict(d)
            for d in _read(PRINCIPLES_F) + _read(PRINCIPLES_INGESTED_F)]


def _next_id(prefix: str, existing: list[str]) -> str:
    n = 1 + max((int(x[len(prefix):]) for x in existing
                 if x.startswith(prefix) and x[len(prefix):].isdigit()), default=0)
    return f"{prefix}{n:03d}"


def save_source(source: Source) -> None:
    """Append a manager-contributed source to the ingested overlay (insert/replace
    by source_id). Never touches the committed seed."""
    rows = [r for r in _read(SOURCES_INGESTED_F) if r.get("source_id") != source.source_id]
    rows.append(asdict(source))
    _write(SOURCES_INGESTED_F, rows)


def save_principle(principle: Principle) -> None:
    """Append a manager-authored principle to the ingested overlay (insert/replace
    by principle_id). Enters the existing review queue as a 'candidate'."""
    rows = [r for r in _read(PRINCIPLES_INGESTED_F)
            if r.get("principle_id") != principle.principle_id]
    rows.append(principle.to_dict())
    _write(PRINCIPLES_INGESTED_F, rows)


def next_source_id() -> str:
    """Next manager-note source id (M-prefixed, so it never collides with seed
    interview 'I…' / survey 'S…' ids)."""
    return _next_id("M", [s.source_id for s in all_sources()])


def next_principle_id() -> str:
    return _next_id("P", [p.principle_id for p in all_principles()])


def get_principle(principle_id: str) -> Principle | None:
    return next((p for p in all_principles() if p.principle_id == principle_id), None)


def approved_principles() -> list[Principle]:
    return [p for p in all_principles() if p.status == "approved"]


# --- generated items (read/write) ------------------------------------------
def all_items() -> list[GeneratedItem]:
    return [GeneratedItem.from_dict(d) for d in _read(ITEMS_F)]


def get_item(item_id: str) -> GeneratedItem | None:
    return next((i for i in all_items() if i.item_id == item_id), None)


def next_item_id() -> str:
    existing = [i.item_id for i in all_items()]
    n = 1 + max((int(x[1:]) for x in existing if x[1:].isdigit()), default=0)
    return f"G{n:04d}"


def save_item(item: GeneratedItem) -> None:
    """Insert or replace by item_id, then persist the whole file."""
    rows = _read(ITEMS_F)
    rows = [r for r in rows if r.get("item_id") != item.item_id]
    rows.append(item.to_dict())
    rows.sort(key=lambda r: r["item_id"])
    _write(ITEMS_F, rows)


def approved_items(tags: list[str] | None = None,
                   query: str = "") -> list[GeneratedItem]:
    """Approved items only — the ONLY items the Coach is allowed to surface.
    Optional tag/keyword filter mirrors retrieval.playbook scoring."""
    tags = [t for t in (tags or []) if t]
    q = (query or "").strip()
    out = []
    for it in all_items():
        if it.review.status != STATUS_APPROVED or not it.provenance.grounding_passed:
            continue
        score = 0
        for t in tags:
            if any(t in et or et in t for et in it.tags):
                score += 3
        for et in it.tags:
            if q and et in q:
                score += 2
        if q and any(tok and tok in it.scenario for tok in q.split()):
            score += 1
        out.append((score, it))
    out.sort(key=lambda x: (x[0], x[1].item_id), reverse=True)
    # if a filter was supplied, drop zero-score; else return all approved
    if tags or q:
        out = [t for t in out if t[0] > 0]
    return [it for _, it in out]
