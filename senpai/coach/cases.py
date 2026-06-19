"""Similar Past Cases — teach through real organizational experience.

A read-only retrieval layer over the *closed* deals in the store (won =
`1_Confirmed`, lost = `7_Lost`/`8_Cancelled`). Given a junior's note (and the
optional deal it relates to), it surfaces a few real past deals whose situation
rhymes with the current one, each tagged with its outcome and the validated
principle it illustrates.

This adds NO new business logic to scoring or coaching — it only *queries and
ranks existing records* and attaches the relevant approved principle. The
"lesson" of each case is an existing, interview-traceable principle, never a
synthesized claim. Presentation/translation happens entirely on the frontend;
this returns structured, language-neutral facts plus principle ids.
"""
from __future__ import annotations

from datetime import date

from senpai import config
from senpai.data import store

# Which validated principle each situational theme teaches. Every id here exists
# in the knowledge store (P001–P011), so a case's "lesson" is always grounded in
# human-approved, interview-traceable knowledge — not invented advice.
THEME_PRINCIPLES: dict[str, list[str]] = {
    "no_decision_maker": ["P003", "P006"],
    "discounting":       ["P002"],
    "stalled":           ["P001"],
    "budget":            ["P005"],
    "discovery":         ["P008", "P010"],
    "disciplined_close": ["P001", "P010"],
}

# Note cues that make a past theme relevant to the current situation.
_THEME_CUES: dict[str, list[str]] = {
    "no_decision_maker": ["決裁", "部長", "社長", "役員", "担当", "キーマン", "decision", "maker"],
    "discounting":       ["値引き", "価格", "高い", "コスト", "ディスカウント", "discount", "price"],
    "stalled":           ["検討", "先送り", "保留", "返事", "また連絡", "stall", "delay"],
    "budget":            ["予算", "費用", "資金", "budget"],
    "discovery":         ["初回", "ヒアリング", "環境", "課題", "discovery", "first visit"],
}


def _has_decision_maker(acts: list[dict]) -> bool:
    """A decision-maker was met if any activity's business card title qualifies."""
    for a in acts:
        title = a.get("business_card_info") or ""
        if any(t in title for t in config.DECISION_MAKER_TITLES):
            return True
    return False


def _was_discounted(deal_id: str) -> bool:
    """Material discounting anywhere on the deal's quote or order lines (>10%)."""
    q = store.quote_for_deal(deal_id)
    if q and (q.get("discount_rate") or 0) > 10:
        return True
    return any((o.get("discount_rate") or 0) > 10 for o in store.orders_for_deal(deal_id))


def _theme_for_deal(deal: dict, acts: list[dict], won: bool) -> str:
    """The single situational lesson a closed deal best illustrates."""
    if won:
        return "disciplined_close"
    # Lost deals: pick the most instructive gap, in priority order.
    if not _has_decision_maker(acts):
        return "no_decision_maker"
    if _was_discounted(deal["deal_id"]):
        return "discounting"
    if (deal.get("comment_count") or 0) == 0 or len(acts) <= 2:
        return "stalled"
    return "stalled"


def _outcome(rank: str | None) -> str | None:
    if rank in config.WON_RANKS:
        return "won"
    if rank in config.DEAD_RANKS:
        return "lost"
    return None


def find_similar_cases(note: str, deal: dict | None = None,
                       max_n: int = 3, today: date | None = None) -> list[dict]:
    """Return up to `max_n` closed deals similar to the current situation, mixing
    wins and losses for contrast. Each case is language-neutral facts + the
    principle ids it teaches; the frontend renders the localized summary."""
    today = today or config.today()
    text = note or ""
    target_cat = (deal or {}).get("product_category")
    note_cat_hit = {c for c in _category_vocab() if c and c in text}

    scored: list[tuple[float, dict]] = []
    for d in store.all_deals():
        if deal is not None and d["deal_id"] == deal["deal_id"]:
            continue
        outcome = _outcome(d.get("order_rank"))
        if outcome is None:
            continue  # only *closed* deals are "past cases"
        acts = store.activities_for_deal(d["deal_id"])
        won = outcome == "won"
        theme = _theme_for_deal(d, acts, won)

        score = 0.5  # baseline so we can always show *some* experience
        cat = d.get("product_category")
        if cat and (cat == target_cat or cat in note_cat_hit):
            score += 3
        # Thematic resonance: does the note talk about what this case teaches?
        for cue in _THEME_CUES.get(theme, []):
            if cue in text:
                score += 1.5
                break
        # Lost deals are slightly favoured — failures teach more vividly.
        if not won:
            score += 0.3

        scored.append((score, {
            "deal_id": d["deal_id"],
            "customer": store.customer_name(d["customer_id"]),
            "product_category": cat or "",
            "amount": d.get("total_order_amount", 0) or 0,
            "outcome": outcome,
            "theme": theme,
            "principle_ids": THEME_PRINCIPLES.get(theme, []),
            "decision_maker": _has_decision_maker(acts),
            "discounted": _was_discounted(d["deal_id"]),
            "n_activities": len(acts),
        }))

    scored.sort(key=lambda s: s[0], reverse=True)
    ordered = [c for _, c in scored]

    # Ensure a teaching mix: guarantee at least one win and one loss if available.
    picked: list[dict] = []
    for want in ("lost", "won"):
        nxt = next((c for c in ordered if c["outcome"] == want and c not in picked), None)
        if nxt:
            picked.append(nxt)
    for c in ordered:
        if len(picked) >= max_n:
            break
        if c not in picked:
            picked.append(c)
    return picked[:max_n]


def _category_vocab() -> set[str]:
    return {d.get("product_category") for d in store.all_deals() if d.get("product_category")}
