"""Grounded generation — turn ONE validated principle into a draft coaching item.

Hard rules enforced here:
  * The model is given ONLY the approved principle (+ its source quotes). It may
    invent a *fictional scenario* to situate the principle, but every signal /
    question / risk it emits must be entailed by the principle, not new advice.
  * Output always lands as STATUS_DRAFT — nothing is shown to a junior until a
    human approves it (see knowledge.review).
  * A pre-screen (`ground_check`) catches the cheap hallucinations — invented
    numbers/percentages/prices and empty scenarios — and marks grounding_passed.
    It is a *gate before* human review, never a replacement for it.
  * If the model server is down or returns garbage, we still emit a deterministic
    skeleton item (scenario from the principle) so the pipeline runs offline; it
    just stays unverified until a human fills it in.
"""
from __future__ import annotations

import json
import re

from senpai.knowledge import store
from senpai.knowledge.schema import (
    GeneratedItem, Principle, Provenance, Review,
)

PROMPT_VERSION = "kx-v1"

# Things that, if they appear in a generated *advice* field, almost always mean
# the model invented a specific it was never given (a number, money, a percent).
_INVENTED = re.compile(r"\d+\s*[%％]|\d[\d,]*\s*円|\d+\s*(社|名|日|割|倍)")


def build_prompt(principle: Principle) -> str:
    quotes = "\n".join(f"- 「{c.quote}」(出典 {c.source_id})" for c in principle.support)
    return (
        "あなたは営業研修の教材作成者です。下記の『検証済み原則』を新人に教えるための"
        "練習シナリオを1つ作ります。\n"
        "厳守事項:\n"
        "1. 原則に含まれない新しい助言・数値・固有名詞を一切足さないこと。\n"
        "2. シナリオは架空の状況でよいが、signals/questions/risks は原則から導ける"
        "範囲に限ること。\n"
        "3. alternatives には『状況によっては別の見方もある』点を1〜2個挙げること"
        "(単一の正解にしない)。\n"
        "4. 出力は次のJSONのみ: "
        '{"scenario": "...", "signals": ["..."], "questions": ["..."], '
        '"risks": ["..."], "alternatives": ["..."]}\n\n'
        f"検証済み原則: {principle.statement}\n"
        f"根拠となる発言:\n{quotes}\n"
    )


def _skeleton(principle: Principle) -> dict:
    """Offline fallback — restates the principle, adds nothing."""
    return {
        "scenario": f"(要編集)『{principle.statement}』が当てはまる場面を想定してください。",
        "signals": [principle.statement],
        "questions": [],
        "risks": [],
        "alternatives": ["状況によっては原則の適用が異なる場合があります。"],
    }


def _parse(raw: str) -> dict | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        d = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def ground_check(item: GeneratedItem, principle: Principle) -> tuple[bool, str]:
    """Cheap hallucination pre-screen. Passes only if there's a real scenario and
    no invented specifics in the advice-bearing fields. NOT a substitute for human
    review — it just stops the obvious failures from reaching a reviewer."""
    if not item.scenario.strip() or "要編集" in item.scenario:
        return False, "シナリオが空、または要編集のまま。"
    advice = item.signals + item.questions + item.risks + item.alternatives
    if not advice:
        return False, "signals/questions/risks がすべて空。"
    for line in advice:
        hit = _INVENTED.search(line)
        if hit and hit.group() not in principle.statement:
            return False, f"原則にない具体数値の可能性: 「{hit.group()}」"
    if not item.alternatives:
        return False, "alternatives(別の見方)が無い — 単一の正解になっている。"
    return True, "自動チェック通過(人手レビュー待ち)。"


def generate_item(principle: Principle, use_llm: bool = True,
                  model: str = "") -> GeneratedItem:
    """Generate ONE draft item from an approved principle. Always returns a
    STATUS_DRAFT item with full provenance; never raises."""
    payload = None
    if use_llm:
        try:
            from senpai.llm import client
            from senpai import config
            model = model or config.MODEL
            raw = client.simple_complete(
                [{"role": "user", "content": build_prompt(principle)}])
            payload = _parse(raw)
        except Exception:  # noqa: BLE001 — server down → deterministic skeleton
            payload = None
    if payload is None:
        payload = _skeleton(principle)
        model = model or "offline-skeleton"

    item = GeneratedItem(
        item_id=store.next_item_id(),
        scenario=str(payload.get("scenario", "")).strip(),
        signals=[s for s in payload.get("signals", []) if s],
        questions=[q for q in payload.get("questions", []) if q],
        risks=[r for r in payload.get("risks", []) if r],
        alternatives=[a for a in payload.get("alternatives", []) if a],
        tags=list(principle.tags),
        provenance=Provenance(
            principle_id=principle.principle_id,
            interview_ids=principle.interview_ids,
            generator_model=model,
            prompt_version=PROMPT_VERSION,
        ),
        review=Review(),  # STATUS_DRAFT
    )
    passed, notes = ground_check(item, principle)
    item.provenance.grounding_passed = passed
    item.provenance.grounding_notes = notes
    return item
