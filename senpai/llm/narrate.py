"""LLM narration of deal health — with a templated fallback.

Turns a deal's deterministic signals/flags into a one-line manager flag plus a
suggested next action (Japanese). exp3 only phrases the 'why'; it never produces
the score. If the model server is unreachable, `narrate_deal` degrades to a
templated string assembled from the signal reasons — so the dashboard always
renders something useful, scoring untouched (the demo's 'never breaks' rule).
"""
from __future__ import annotations

from senpai.health.flags import Flag
from senpai.health.scoring import HealthResult
from senpai.llm import client

_EMOJI = {"red": "🔴", "yellow": "🟡", "green": "🟢"}


def _templated(deal: dict, health: HealthResult, flags: list[Flag]) -> str:
    """Deterministic fallback — no model needed."""
    emoji = _EMOJI.get(health.band, "")
    reasons = health.top_reasons(3)
    why = "／".join(reasons) if reasons else "目立ったリスクなし"
    if health.band == "red":
        action = "上長同席で再提案を打診し、次回の意思決定事項を確定する。"
    elif health.band == "yellow":
        action = "次回接触日を設定し、停滞要因を一つ潰す。"
    else:
        action = "現状維持。次の一歩を予定どおり進める。"
    return f"{emoji} {why} → {action}"


def narrate_deal(deal: dict, health: HealthResult, flags: list[Flag],
                 use_llm: bool = True) -> str:
    """Return a one-line JP flag + suggested action. Uses exp3 when reachable,
    else the templated fallback."""
    fallback = _templated(deal, health, flags)
    if not use_llm:
        return fallback
    reasons = "、".join(health.top_reasons(3)) or "なし"
    flag_msgs = "、".join(f.message for f in flags) or "なし"
    prompt = (
        "あなたは営業マネージャー向けのアシスタントです。以下の案件について、"
        "1行で(1)状況フラグと(2)推奨アクションを日本語で簡潔に示してください。"
        "数字は与えられたものだけを使い、創作しないこと。\n"
        f"健全度: {health.band}(リスク{health.score}/100)\n"
        f"リスク要因: {reasons}\n"
        f"信頼性フラグ: {flag_msgs}\n"
        f"先頭に {_EMOJI.get(health.band, '')} を付けてください。"
    )
    try:
        out = client.simple_complete([{"role": "user", "content": prompt}])
        return out or fallback
    except Exception:  # noqa: BLE001 — server down → templated fallback
        return fallback
