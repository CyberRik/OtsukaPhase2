"""generate_proposal — a persuasive PPTX sales proposal, grounded in a deal's SPR data.

Follows Otsuka's proposal arc: (1) 表紙, (2) 背景/なぜ今, (3) 課題 (pain points from SPR
customer_challenge), (4) ソリューション (matched catalog products), (5) 投資対効果 (the
deal's real financials + comparable deals), (6) 次のステップ. Every number, product,
price, and comparable comes straight from context.py; the persuasive FRAMING is layered
by narrative.proposal_prose (LLM when available, grounded templated fallback otherwise),
so nothing is invented. Renders via render.py.

Smoke:  python -m senpai.documents.proposal D001
"""
from __future__ import annotations

from pathlib import Path

from senpai.documents import narrative
from senpai.documents.context import DocumentContext, build_document_context
from senpai.documents.render import output_path, render_pptx


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return "¥0"


def build_proposal_spec(ctx: DocumentContext, lang: str = "ja") -> dict:
    """Build a persuasive, grounded proposal deck from a DocumentContext.

    Follows Otsuka's proposal arc (表紙 → 背景/なぜ今 → 課題 → ソリューション →
    投資対効果 → 次のステップ). Persuasive FRAMING comes from narrative.proposal_prose
    (LLM when available, grounded templated fallback otherwise); every NUMBER, product,
    price, and comparable stays deterministic from ctx, so nothing is invented."""
    prose = narrative.proposal_prose(ctx, lang=lang)

    # Slide 1 — 表紙
    title_slide = {
        "layout": "title",
        "title": f"{ctx.customer}様 ご提案",
        "subtitle": f"{prose['catch']}\n{ctx.product_category}　|　{ctx.today}　|　担当: {ctx.rep}",
    }

    # Slide 2 — 背景・なぜ今
    background_slide = {
        "layout": "content",
        "title": "背景 — なぜ今、取り組むべきか",
        "bullets": prose["why_now"],
        "notes": "業界動向とタイミングの整理（顧客の課題に基づく framing）。",
    }

    # Slide 3 — 課題（framing 済み、but grounded in the real pain points）
    challenge_slide = {
        "layout": "content",
        "title": "課題 — 現状のお困りごと",
        "bullets": prose["challenges"],
        "notes": "SPRの日報・customer_challengeから抽出した実際の課題を framing。",
    }

    # Slide 4 — ソリューション（framing + the real catalog products/prices）
    sol_bullets = list(prose["solution"])
    for p in ctx.products[:4]:
        sol_bullets.append(f"{p['name']}（{p['code']}）— {_yen(p['price'])}")
    solution_slide = {
        "layout": "content",
        "title": f"ソリューション — {ctx.product_category}",
        "bullets": sol_bullets,
        "notes": "便益は framing、製品・価格は大塚商会カタログの実データ。",
    }

    # Slide 5 — 投資対効果（real numbers + value framing + real comparables）
    f = ctx.financials
    # Lead with the REAL commercial number: if a quote is on file, show the actual
    # proposed price and the discount already extended (標準 → ご提案価格), not the
    # undiscounted list price. Fall back to the order amount when there is no quote.
    quoted = f.get("quote_amount")
    standard = f.get("standard_amount") or f.get("investment", 0)
    if quoted and standard and quoted != standard:
        disc = f.get("discount_rate")
        disc_txt = f"（標準 {_yen(standard)} より{disc}%割引）" if disc else f"（標準 {_yen(standard)}）"
        roi_bullets = [f"ご提案価格: {_yen(quoted)}{disc_txt}"]
    elif quoted:
        roi_bullets = [f"ご提案価格: {_yen(quoted)}"]
    else:
        roi_bullets = [f"投資額: {_yen(f.get('investment', 0))}"]
    breakdown = []
    if f.get("hw_revenue"):
        breakdown.append(f"ハードウェア {_yen(f['hw_revenue'])}")
    if f.get("sw_revenue"):
        breakdown.append(f"ソフトウェア {_yen(f['sw_revenue'])}")
    if f.get("service_revenue"):
        breakdown.append(f"サービス {_yen(f['service_revenue'])}")
    if breakdown:
        # The breakdown sums to the standard amount; label it so it reads
        # consistently under a discounted ご提案価格 headline.
        label = "内訳（標準構成）" if (quoted and standard and quoted != standard) else "内訳"
        roi_bullets.append(label + ": " + " / ".join(breakdown))
    roi_bullets.extend(prose["value"])
    for c in ctx.comparables:
        roi_bullets.append(
            f"参考事例: {c['customer']}（{c['product_category']}）{_yen(c['amount'])}・{c['outcome']}")
    roi_slide = {
        "layout": "content",
        "title": "投資対効果",
        "bullets": roi_bullets,
        "notes": "金額はすべてSPRの実データ。参考事例は同カテゴリの実案件（創作なし）。",
    }

    # Slide 6 — 次のステップ
    next_slide = {
        "layout": "content",
        "title": "次のステップ",
        "bullets": prose["next_steps"],
        "notes": "丁寧な依頼文体で次の一歩を提示。",
    }

    return {"slides": [title_slide, background_slide, challenge_slide,
                       solution_slide, roi_slide, next_slide]}


def generate(deal_id: str, lang: str = "ja") -> tuple[Path, DocumentContext, dict] | None:
    """Build + render a proposal for `deal_id`. Returns (path, context, spec) or None.
    The spec is returned so the caller can show the exact outline that was rendered
    without re-authoring it (which, with the LLM prose pass, would be a second call
    and could differ from the file)."""
    ctx = build_document_context(deal_id)
    if ctx is None:
        return None
    spec = build_proposal_spec(ctx, lang=lang)
    path = output_path("proposal", deal_id, "pptx")
    render_pptx(spec, path)
    return path, ctx, spec


if __name__ == "__main__":
    import sys

    did = sys.argv[1] if len(sys.argv) > 1 else "D001"
    out = generate(did)
    if out is None:
        print(f"deal {did} not found")
    else:
        p, c, _spec = out
        print(f"wrote {p}  ({p.stat().st_size} bytes) for {c.customer}")
