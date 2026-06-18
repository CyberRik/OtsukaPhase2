"""The human review gate — the only path an item takes to becoming shown.

A draft item is invisible to juniors. A reviewer (a senior, or a trainer who
checked it against the source interview) approves / asks-for-edit / rejects it.
Approval is what flips an item into the Coach's approved pool, and confidence is
re-derived from the backing principle at that moment. Every transition is
recorded with who and when, so provenance survives.
"""
from __future__ import annotations

from senpai.knowledge import store
from senpai.knowledge.schema import (
    STATUS_APPROVED, STATUS_NEEDS_EDIT, STATUS_REJECTED, _now,
)


def _set_status(item_id: str, status: str, reviewer: str, notes: str):
    item = store.get_item(item_id)
    if item is None:
        raise KeyError(item_id)
    item.review.status = status
    item.review.reviewer = reviewer
    item.review.reviewed_at = _now()
    item.review.notes = notes
    store.save_item(item)
    return item


def approve(item_id: str, reviewer: str, notes: str = ""):
    """Approve — only meaningful if grounding passed; otherwise this is a reviewer
    explicitly overriding, recorded as such in notes."""
    item = store.get_item(item_id)
    if item and not item.provenance.grounding_passed and "override" not in notes:
        notes = (notes + " [override: grounding未通過を人手承認]").strip()
        # a reviewer may still approve, but we force grounding_passed so the
        # confidence + visibility rules treat it as vetted by a human.
        item.provenance.grounding_passed = True
        store.save_item(item)
    return _set_status(item_id, STATUS_APPROVED, reviewer, notes)


def request_edit(item_id: str, reviewer: str, notes: str):
    return _set_status(item_id, STATUS_NEEDS_EDIT, reviewer, notes)


def reject(item_id: str, reviewer: str, notes: str = ""):
    return _set_status(item_id, STATUS_REJECTED, reviewer, notes)


def pending() -> list:
    """Items awaiting a human decision (draft or needs_edit), grounding-passed
    first so reviewers triage the clean ones fast."""
    items = [i for i in store.all_items()
             if i.review.status in ("draft", STATUS_NEEDS_EDIT)]
    return sorted(items, key=lambda i: (not i.provenance.grounding_passed, i.item_id))
