"""Account commentary context + prompt.

`build_account_context` renders the deterministic AccountSummary into a compact,
grounded text package (every line traces to a record); `account_commentary_prompt`
asks the served model for a senior *account manager's* read over it — the same
strict-grounding contract as the deal-level Senior Commentary, but reasoning over
the whole relationship instead of one opportunity. Streams via the existing
llm.client path; callers fall back to the deterministic summary on any failure.
"""
from __future__ import annotations

from datetime import date

from senpai import config
from senpai.data import store
from senpai.health.scoring import score_deal

from senpai.account.summary import build_account_summary, AccountSummary


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (ValueError, TypeError):
        return "¥0"


def _open_deal_lines(customer_id: str, today: date) -> list[str]:
    """Open deals with their per-deal health band, so the account read can refer
    to a specific stalled deal by id (the deal↔account cross-link)."""
    lines: list[str] = []
    for d in store.deals_for_customer(customer_id):
        if not config.is_open_rank(d.get("order_rank")):
            continue
        acts = store.activities_for_deal(d["deal_id"])
        res = score_deal(d, acts, today=today)
        lines.append(
            f"  - {d['deal_id']}: {d.get('product_category','-')} | rank "
            f"{d.get('order_rank','-')} | {_yen(d.get('total_order_amount',0))} | "
            f"health {res.band}")
    return lines


def build_account_context(customer_id: str, today: date | None = None,
                          lang: str = "ja") -> tuple[str, dict]:
    """Return (context_text, meta). meta carries has_account/customer/score/band."""
    today = today or config.today()
    s: AccountSummary | None = build_account_summary(customer_id, today=today)
    if s is None:
        meta = {"has_account": False, "customer": None, "customer_id": customer_id,
                "score": None, "band": None}
        return ("NO MATCHING ACCOUNT FOUND. Do not invent any account facts.", meta)

    h = s.health
    meta = {"has_account": True, "customer": s.customer, "customer_id": customer_id,
            "score": h.get("score"), "band": h.get("band")}

    lines: list[str] = []
    lines.append(f"ACCOUNT: {s.customer} (industry: {s.industry}, size: {s.size})")
    lines.append(
        f"DEALS: {s.active_deals} active / {s.won_deals} won / {s.lost_deals} lost")
    lines.append(f"PIPELINE: {_yen(s.total_pipeline)} open | "
                 f"HISTORICAL REVENUE: {_yen(s.historical_revenue)}")
    lines.append(f"ACCOUNT HEALTH: {h.get('band')} ({h.get('score')}/100, higher=healthier)")
    # the dimensions dragging the score down — gives the model concrete reasons
    weak = sorted(h.get("dimensions", []), key=lambda d: d["points"] / d["max"] if d["max"] else 1)[:3]
    if weak:
        lines.append("  weakest dimensions: " + "; ".join(d["reason"] for d in weak))
    lines.append(f"ACTIVITY TREND: {s.activity_trend}"
                 + (f" | last activity {s.last_activity}" if s.last_activity else ""))

    open_lines = _open_deal_lines(customer_id, today)
    if open_lines:
        lines.append("OPEN DEALS:")
        lines.extend(open_lines)

    if s.recent_orders:
        lines.append("RECENT ORDERS:")
        for o in s.recent_orders:
            lines.append(f"  - {o.get('ordered_at','?')} {o.get('product','-')} "
                         f"{_yen(o.get('amount',0))}")
    else:
        lines.append("RECENT ORDERS: none on record")

    if s.recent_quotes:
        lines.append("RECENT QUOTES:")
        for q in s.recent_quotes:
            disc = f" (discount {q['discount_rate']}%)" if q.get("discount_rate") else ""
            lines.append(f"  - {q.get('quoted_at','?')} {q.get('product','-')} "
                         f"{_yen(q.get('amount',0))}{disc} [{q.get('order_flag','-')}]")

    if s.environment:
        lines.append(f"IT ENVIRONMENT: {s.environment}")

    if s.risk_signals:
        lines.append("RISK SIGNALS (relationship trajectory):")
        lines.extend(f"  - [{p['id']}] {p['label_ja']} — {p['evidence']}"
                     for p in s.risk_signals)
    if s.expansion_signals:
        lines.append("EXPANSION SIGNALS:")
        for e in s.expansion_signals:
            label = e.get("label_ja") or f"{e.get('kind','')}→{e.get('target','')}"
            ev = e.get("evidence") or e.get("rationale", "")
            lines.append(f"  - {label} — {ev}")

    lines.append(f"RECOMMENDED FOCUS (deterministic): {s.recommended_focus}")
    return "\n".join(lines), meta


def account_commentary_prompt(context_text: str, lang: str = "ja") -> str:
    """Senior account-manager read over the whole relationship — NOT a restatement
    of the summary. Strict grounding: use only the context, quote numbers exactly,
    cite Pxxx principles and the [pattern_id]s where they fit, never invent."""
    if lang == "en":
        return (
            "You are an experienced sales manager reviewing an entire CUSTOMER "
            "ACCOUNT (not one deal). Give your honest read of the relationship.\n\n"
            "Write natural, conversational English under exactly these four short "
            "headings (1–2 sentences each):\n"
            "**Account Reality** — how healthy is this relationship, really?\n"
            "**Single Deal vs the Whole Account** — where does the account picture "
            "differ from any one stalled/active deal? Refer to specific deal ids.\n"
            "**The Real Risk (intent vs access)** — is the risk customer intent, or "
            "something else (decision-maker access, progression, dormancy)?\n"
            "**Recommended Focus** — one or two concrete account-level moves.\n\n"
            "Rules: ground every statement in the CONTEXT; quote its numbers EXACTLY "
            "(counts, ¥ amounts, days, score). Refer to risk/expansion signals by "
            "their [id]. Never invent facts. Be concise: ~120–170 words.\n\n"
            f"ACCOUNT CONTEXT (from records):\n{context_text}"
        )
    return (
        "あなたは経験豊富な営業マネージャーです。個別の案件ではなく、顧客アカウント"
        "全体の関係性を率直に読んでください。\n\n"
        "自然な会話調の日本語で、次の4つの短い見出し（各1〜2文）で書いてください:\n"
        "**アカウントの実態** — この関係性は実際どれくらい健全か？\n"
        "**個別案件 vs 全体** — 停滞中・進行中の個別案件と、アカウント全体像はどこが"
        "食い違うか。具体的な案件ID（例: D001）に触れること。\n"
        "**本当のリスク（意図 vs アクセス）** — リスクは顧客の購買意図か、それとも"
        "別の要因（決裁者アクセス・案件の前進・休眠化）か。\n"
        "**推奨アクション** — アカウント単位の具体的な一手を1〜2個。\n\n"
        "ルール: すべての記述を文脈の事実に基づかせ、数字（件数・金額・日数・スコア）は"
        "文脈どおり正確に引用すること。リスク/拡大シグナルは [id] で参照すること。"
        "事実を創作しないこと。簡潔に、前置きなしで合計160〜240文字程度。\n\n"
        f"アカウント文脈（記録より）:\n{context_text}"
    )
