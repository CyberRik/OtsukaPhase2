"""Tests for the responsible knowledge-expansion pipeline (no GPU, no model).

Locks the guarantees that matter: confidence is earned not authored, the
grounding pre-screen catches invented specifics, generation always lands as an
unverified draft, only human approval makes an item visible, and the Coach
surfaces ONLY approved, interview-traceable items.
"""
from __future__ import annotations

import pytest

from senpai.knowledge import generate, review, store
from senpai.knowledge.schema import (
    CONF_HIGH, CONF_LOW, CONF_MEDIUM, CONF_UNVERIFIED, STATUS_APPROVED,
    Citation, GeneratedItem, Principle, Provenance, Review,
)


@pytest.fixture
def tmp_items(tmp_path, monkeypatch):
    """Redirect the writable items file to a temp path so tests never touch seed."""
    f = tmp_path / "generated_items.json"
    f.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(store, "ITEMS_F", f)
    return f


def _principle(*interviews, surveys=False) -> Principle:
    return Principle(
        principle_id="P001",
        statement="顧客が即答を避けるときは決裁プロセスと次の期日を確認する。",
        support=[Citation(s, "...", "") for s in interviews],
        corroborating_surveys=[Citation("S01", "...", "")] if surveys else [],
        tags=["決裁者未特定"],
        status="approved",
    )


def _approved_item(principle, **over) -> GeneratedItem:
    it = GeneratedItem(
        item_id="G0001",
        scenario="ある中小企業の担当者が『社内で検討します』と即答を避けた。",
        signals=["決裁者が誰か不明"],
        questions=["どなたが最終決定されますか？"],
        risks=["期日がなく自然消滅しやすい"],
        alternatives=["関係構築の初期なら一旦持ち帰りを尊重する選択もある"],
        tags=list(principle.tags),
        provenance=Provenance(principle_id="P001",
                              interview_ids=principle.interview_ids,
                              grounding_passed=True),
        review=Review(status=STATUS_APPROVED, reviewer="senior_a"),
    )
    for k, v in over.items():
        setattr(it, k, v)
    return it


# --- confidence is computed, not authored ----------------------------------
def test_confidence_unverified_until_approved():
    p = _principle("I01", "I02")
    it = _approved_item(p, review=Review(status="draft"))
    assert it.confidence(p) == CONF_UNVERIFIED


def test_confidence_high_needs_two_interviews():
    assert _approved_item(_principle("I01", "I02")).confidence(_principle("I01", "I02")) == CONF_HIGH


def test_confidence_low_for_single_thin_interview():
    p = _principle("I01")
    assert _approved_item(p).confidence(p) == CONF_LOW


def test_confidence_medium_when_survey_corroborates():
    p = _principle("I01", surveys=True)
    assert _approved_item(p).confidence(p) == CONF_MEDIUM


# --- grounding pre-screen ---------------------------------------------------
def test_ground_check_rejects_invented_numbers():
    p = _principle("I01")
    it = _approved_item(p, risks=["成約率は80%上がる"])  # number not in principle
    passed, notes = generate.ground_check(it, p)
    assert not passed and "数値" in notes


def test_ground_check_requires_alternatives():
    p = _principle("I01")
    it = _approved_item(p, alternatives=[])
    passed, _ = generate.ground_check(it, p)
    assert not passed


def test_ground_check_passes_clean_item():
    p = _principle("I01")
    assert generate.ground_check(_approved_item(p), p)[0] is True


# --- generation always yields an unverified draft --------------------------
def test_offline_generation_is_draft_and_unverified(tmp_items):
    p = _principle("I01", "I02")
    item = generate.generate_item(p, use_llm=False)
    assert item.review.status == "draft"
    assert item.provenance.principle_id == "P001"
    assert item.provenance.interview_ids == ["I01", "I02"]
    # the offline skeleton must NOT pass grounding (it's a 要編集 stub)
    assert item.provenance.grounding_passed is False
    assert item.confidence(p) == CONF_UNVERIFIED


# --- only human approval makes an item visible -----------------------------
def test_approval_flow_makes_item_visible(tmp_items):
    p = _principle("I01", "I02")
    store.save_item(_approved_item(p, review=Review(status="draft")))
    # draft → not visible
    assert store.approved_items(tags=["決裁者未特定"]) == []
    review.approve("G0001", reviewer="senior_a", notes="原則どおり")
    visible = store.approved_items(tags=["決裁者未特定"])
    assert len(visible) == 1 and visible[0].review.reviewer == "senior_a"


# --- the Coach surfaces only approved, traceable items ---------------------
def test_coach_uses_only_approved_knowledge(tmp_items):
    from senpai.coach.review import review_note
    p = _principle("I01", "I02")
    store.save_item(_approved_item(p))  # already approved + grounded
    r = review_note("お客様は社内で検討してから連絡するとのこと。")
    assert any("先輩の知見" in a and "I01" in a for a in r.next_actions)
