"""Unit tests for the Sales Review Coach engine (no GPU, no model).

The coach is the onboarding core, so these lock its *teaching* behaviour:
gaps in a thin note are surfaced, a thorough note stays quiet, presence
detectors fire, structured deal context reinforces the text, and the output
never collapses to a single 'correct answer'.
"""
from __future__ import annotations

from datetime import timedelta

from senpai import config
from senpai.coach.review import format_review, review_note

TODAY = config.today()

# The canonical thin note from the product spec.
THIN = "お客様は社内で検討してから連絡するとのこと。"


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def test_thin_note_surfaces_the_core_gaps():
    r = review_note(THIN, today=TODAY)
    # decision-maker, timeline and criteria are all unaddressed in the note.
    missing = " ".join(r.missing_info)
    assert "決裁者" in missing
    assert "次回接触日" in missing or "時期" in missing
    assert "判断基準" in missing


def test_thin_note_asks_questions_not_answers():
    r = review_note(THIN, today=TODAY)
    assert len(r.questions) >= 3
    # Several possible moves, framed as options — not one prescribed answer.
    assert len(r.next_actions) >= 2


def test_stall_language_is_detected():
    r = review_note("先方は『検討します』とのことで持ち帰りに。", today=TODAY)
    joined = " ".join(r.observations + r.risks)
    assert "停滞" in joined


def test_competition_becomes_a_decision_factor():
    r = review_note("他社と比較中とのこと。価格を気にされている。", today=TODAY)
    assert any("競合" in f for f in r.decision_factors)
    assert any("比較" in q for q in r.questions)


def test_thorough_note_stays_quiet_on_addressed_dimensions():
    note = ("決裁者は山田部長と確認。次回は来週の打ち合わせで判断基準(価格と保守)を"
            "すり合わせ、見積を提出する予定。予算は確保済み。")
    r = review_note(note, today=TODAY)
    missing = " ".join(r.missing_info)
    assert "決裁者" not in missing
    assert "判断基準" not in missing
    assert "予算" not in missing


def test_deal_context_reinforces_text_reading():
    deal = {
        "deal_id": "D999",
        "stage": "negotiation",
        "stage_history": [{"stage": "negotiation", "entered_date": _iso(120)}],
        "expected_close_date": _iso(20),          # in the past
        "close_date_history": [_iso(50), _iso(35), _iso(20)],
        "last_contact_date": _iso(60),
        "decision_maker_identified": False,
        "rep_close_likelihood": "high",
        "status": "open",
        "amount": 500000,
    }
    notes = [{"date": _iso(60), "text": "また連絡しますとのこと"}]
    r = review_note(THIN, deal=deal, notes=notes, today=TODAY)
    assert r.used_deal
    # structured signals (stale / slips / past close) show up as observations.
    assert any("案件データ上のサイン" in o for o in r.observations)


def test_format_review_is_self_describing_and_never_empty():
    r = review_note(THIN, today=TODAY)
    text = format_review(r)
    assert "正解を一つ示すものではありません" in text
    assert "経験豊富な営業が気づくこと" in text


def test_empty_note_via_tool_is_handled():
    from senpai.tools.impl import review_sales_note
    assert "入力してください" in review_sales_note(note="")
