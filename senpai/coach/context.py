"""Context Retrieval Layer for Senior Commentary.

Before the model is asked for its read, this assembles a *grounded* context
package from the store: the customer, the deal it most likely refers to, its
deterministic health, recent activity, quote/order history, prior deals, and a
similar past case. The model then reasons over real business context — not the
meeting note alone — so commentary can say "59 days inactive, stuck at 3_A for
two months" instead of generic "decision maker unclear".

Hard grounding rule: every fact here comes from an actual store record. Nothing
is inferred or invented. When the note can't be linked to a known customer, that
is stated explicitly so the model knows to read from the note alone and must not
fabricate customer facts.
"""
from __future__ import annotations

import re
from datetime import date

from senpai import config
from senpai.coach.cases import find_similar_cases
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.knowledge import store as kstore

# Deterministic signal/flag reasons are authored in Japanese (the engine stays
# unchanged). For English commentary we render them in English IN THE CONTEXT so
# the model has no Japanese to paste. Mirrors the frontend's coach-line templates.
_FIELD_EN = {"決裁者": "decision-maker", "金額": "amount",
             "完了予定日": "expected order date", "日報": "daily report"}
_SIGNAL_EN: list[tuple[re.Pattern, object]] = [
    (re.compile(r"^(\d+)日間接触なし\(目安(\d+)日の2倍超\)$"),
     lambda m: f"{m[1]} days without contact (over 2x the {m[2]}-day benchmark)"),
    (re.compile(r"^(\d+)日間接触なし\(目安(\d+)日超\)$"),
     lambda m: f"{m[1]} days without contact (over the {m[2]}-day benchmark)"),
    (re.compile(r"^(.+?)に(\d+)日滞留\(目安(\d+)日\)$"),
     lambda m: f"stuck at {m[1]} for {m[2]} days (benchmark {m[3]} days)"),
    (re.compile(r"^完了予定日\((.+?)\)を過ぎても未受注$"),
     lambda m: f"past the expected order date ({m[1]}) with no order yet"),
    (re.compile(r"^ランクが (.+?) → (.+?) に低下$"),
     lambda m: f"rank dropped from {m[1]} -> {m[2]}"),
    (re.compile(r"^決裁者が未特定$"), lambda m: "decision-maker not identified"),
    (re.compile(r"^直近の日報に停滞サイン「(.+?)」$"),
     lambda m: f'stall signal "{m[1]}" in the latest daily report'),
    (re.compile(r"^直近30日の活動が0件$"), lambda m: "no activity in the last 30 days"),
    (re.compile(r"^完了予定日\((.+?)\)を過ぎても案件がオープン$"),
     lambda m: f"past the expected order date ({m[1]}); deal still open"),
    (re.compile(r"^(\d+)日活動がないままアクティブ扱い$"),
     lambda m: f"marked active despite {m[1]} days with no activity"),
    (re.compile(r"^必須項目が未入力: (.+)$"),
     lambda m: "missing required fields: "
               + ", ".join(_FIELD_EN.get(f, f) for f in m[1].split("・"))),
    (re.compile(r"^ランクは『(.+?)』だが健全度は赤$"),
     lambda m: f'rank is "{m[1]}" but health is red'),
    (re.compile(r"^(.+?)への更新を裏づける日報がない$"),
     lambda m: f"no daily report supports the update to {m[1]}"),
]


def _en_signal(s: str) -> str:
    for pat, fn in _SIGNAL_EN:
        m = pat.match(s)
        if m:
            return fn(m)  # type: ignore[operator]
    return s


def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat(d) if d else None
    except (ValueError, TypeError):
        return None


def _days_since(d: str | None, today: date) -> int | None:
    dt = _parse(d)
    return (today - dt).days if dt else None


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (ValueError, TypeError):
        return "¥0"


def match_customer_in_note(note: str) -> dict | None:
    """Find the most specific known customer named in the note — across Japanese,
    English, romaji and alias forms (e.g. 'Aozora Services' -> あおぞらサービス).
    Longest match wins and ambiguous forms resolve to None; the alias-aware logic
    lives in the store so tools and the coach share one resolver."""
    return store.match_customer_in_text(note)


def _pick_deal(customer_id: str) -> dict | None:
    """The deal a note about this customer most likely concerns: prefer an open
    deal, most recently updated; else the most recent deal of any status."""
    deals = store.deals_for_customer(customer_id)
    if not deals:
        return None
    open_deals = [d for d in deals if config.is_open_rank(d.get("order_rank"))]
    pool = open_deals or deals
    return max(pool, key=lambda d: d.get("rank_updated_at")
               or d.get("registered_at") or "")


def _customer_history(customer_id: str, exclude_deal_id: str) -> str:
    deals = [d for d in store.deals_for_customer(customer_id)
             if d["deal_id"] != exclude_deal_id]
    if not deals:
        return "no other deals on record for this customer"
    won = sum(1 for d in deals if d.get("order_rank") in config.WON_RANKS)
    lost = sum(1 for d in deals if d.get("order_rank") in config.DEAD_RANKS)
    open_ = sum(1 for d in deals if config.is_open_rank(d.get("order_rank")))
    return f"{len(deals)} prior deal(s) — {won} won, {lost} lost, {open_} open"


def corpus_knowledge(note: str, principle_ids: list[str], max_n: int = 3) -> list[str]:
    """Approved knowledge-corpus principles relevant to this situation, as
    'P00x: <statement> (source <interview ids>)' lines. Draws from the similar
    case's principle ids plus any approved items matching the note — so the
    model's read can apply validated senior knowledge, never invented advice.
    Every line is interview-traceable; nothing here is synthesized."""
    ids: list[str] = list(dict.fromkeys(principle_ids))
    for it in kstore.approved_items(query=note)[:3]:
        pid = it.provenance.principle_id
        if pid and pid not in ids:
            ids.append(pid)
    lines: list[str] = []
    for pid in ids[:max_n]:
        p = kstore.get_principle(pid)
        if not p:
            continue
        srcs = ", ".join(p.interview_ids)
        lines.append(f"{pid}: {p.statement}" + (f" (source {srcs})" if srcs else ""))
    return lines


def build_commentary_context(note: str, deal_id: str | None = None,
                             today: date | None = None,
                             lang: str = "ja") -> tuple[str, dict]:
    """Return (context_text, meta). `meta` carries has_customer_context and the
    resolved customer/deal for the UI. context_text is the grounded package fed
    to the model (English labels; values verbatim from records). When lang=='en'
    the Japanese signal/flag reasons are rendered in English so the model has no
    Japanese to leak into an English read."""
    today = today or config.today()
    tr = _en_signal if lang == "en" else (lambda s: s)

    deal = store.get_deal(deal_id) if deal_id else None
    customer = None
    if deal is None:
        customer = match_customer_in_note(note)
        if customer:
            deal = _pick_deal(customer["customer_id"])
    if deal is not None and customer is None:
        customer = store.get_customer(deal["customer_id"])

    meta = {
        "has_customer_context": bool(deal),
        "customer": customer.get("name") if customer else None,
        "deal_id": deal["deal_id"] if deal else None,
    }

    if deal is None:
        return (
            "NO MATCHING CUSTOMER OR DEAL FOUND IN RECORDS.\n"
            "The note could not be linked to a known customer. Base the read on "
            "the note text and the coach findings only. Do NOT invent any "
            "customer facts, history, numbers, or deal status.",
            meta,
        )

    acts = store.activities_for_deal(deal["deal_id"])
    res = score_deal(deal, acts, today=today)
    flags = deal_flags(deal, acts, health_band=res.band, today=today)
    last_act = acts[0].get("activity_date") if acts else None
    inactive = _days_since(last_act, today)
    rank_since = _days_since(deal.get("rank_updated_at"), today)
    quote = store.quote_for_deal(deal["deal_id"])
    orders = store.orders_for_deal(deal["deal_id"])

    lines: list[str] = []
    cn = customer.get("name", deal["customer_id"]) if customer else deal["customer_id"]
    ind = customer.get("industry", "?") if customer else "?"
    size = customer.get("size", "?") if customer else "?"
    lines.append(f"CUSTOMER: {cn} (industry: {ind}, size: {size})")
    lines.append(
        f"DEAL {deal['deal_id']}: {deal.get('deal_name', '-')} | "
        f"category {deal.get('product_category', '-')} | "
        f"rank {deal.get('order_rank', '-')} | "
        f"amount {_yen(deal.get('total_order_amount', 0))} | "
        f"expected order {deal.get('expected_order_date', '-')}"
    )
    if rank_since is not None:
        lines.append(f"RANK AGE: at rank {deal.get('order_rank','-')} for {rank_since} days")
    reasons = [tr(r) for r in res.top_reasons(3)]
    lines.append(
        f"DEAL HEALTH: {res.band} (risk {res.score}/100)"
        + (f" — signals: {'; '.join(reasons)}" if reasons else "")
    )
    if flags:
        lines.append("RELIABILITY FLAGS: " + "; ".join(tr(f.message) for f in flags))
    if inactive is not None:
        lines.append(f"INACTIVITY: last activity {last_act} ({inactive} days ago)")
    else:
        lines.append("INACTIVITY: no recorded activity")
    if quote:
        disc = quote.get("discount_rate")
        lines.append("QUOTE: on record"
                     + (f" (discount {disc}%)" if disc else ""))
    else:
        lines.append("QUOTE: none on record")
    lines.append(f"ORDERS: {len(orders)} line(s) on record" if orders
                 else "ORDERS: none on record")
    lines.append("CUSTOMER HISTORY: "
                 + _customer_history(deal["customer_id"], deal["deal_id"]))

    recent = acts[:3]
    if recent:
        lines.append("RECENT ACTIVITY:")
        for a in recent:
            snippet = (a.get("daily_report") or "").strip().replace("\n", " ")
            if len(snippet) > 90:
                snippet = snippet[:90] + "…"
            lines.append(f"  - {a.get('activity_date','?')} "
                         f"[{a.get('activity_type','-')}] {snippet}")

    similar = find_similar_cases(note, deal=deal, max_n=1, today=today)
    sim_pids: list[str] = []
    if similar:
        s = similar[0]
        sim_pids = s["principle_ids"]
        lines.append(
            f"SIMILAR PAST CASE: {s['customer']} ({s['product_category']}) "
            f"— {s['outcome']}; teaches principle(s) {', '.join(s['principle_ids'])}"
        )

    corpus = corpus_knowledge(note, sim_pids)
    if corpus:
        lines.append("RELEVANT CORPUS KNOWLEDGE (validated senior principles — "
                     "apply where they fit, cite the Pxxx id):")
        lines.extend(f"  - {c}" for c in corpus)

    return "\n".join(lines), meta
