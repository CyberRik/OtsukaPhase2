"""generate_proposal — a 4-slide PPTX sales proposal, grounded in a deal's SPR data.

Slides: (1) Title, (2) 課題 (pain points from SPR customer_challenge),
(3) ソリューション (matched catalog products), (4) 投資対効果＆次のステップ (the deal's
real financials + comparable deals). Numbers come straight from context.py; only the
title value-proposition line is (optionally) LLM-phrased. Renders via render.py.

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
    """Build the 4-slide deck spec from a grounded DocumentContext."""
    value_prop = narrative.proposal_value_prop(ctx, lang=lang)

    # Slide 1 — title
    title_slide = {
        "layout": "title",
        "title": f"{ctx.customer}様 ご提案",
        "subtitle": f"{value_prop}\n{ctx.product_category}　|　{ctx.today}　|　担当: {ctx.rep}",
    }

    # Slide 2 — 課題
    pains = ctx.pain_points[:5] or ["（SPRに記録された明確な課題はありません）"]
    challenge_slide = {
        "layout": "content",
        "title": "課題 — 現状のお困りごと",
        "bullets": [f"{p}" for p in pains],
        "notes": "SPRの日報・customer_challengeから抽出した実際の課題です。",
    }

    # Slide 3 — ソリューション
    if ctx.products:
        sol_bullets = [f"{p['name']}（{p['code']}）— {_yen(p['price'])}" for p in ctx.products[:5]]
    else:
        sol_bullets = [f"{ctx.product_category} を中心としたご提案"]
    solution_slide = {
        "layout": "content",
        "title": f"ソリューション — {ctx.product_category}",
        "bullets": sol_bullets,
        "notes": "大塚商会の取扱製品（カタログ）から該当カテゴリを抽出。",
    }

    # Slide 4 — 投資対効果 & 次のステップ
    f = ctx.financials
    roi_bullets = [f"投資額: {_yen(f.get('investment', 0))}"]
    breakdown = []
    if f.get("hw_revenue"):
        breakdown.append(f"ハードウェア {_yen(f['hw_revenue'])}")
    if f.get("sw_revenue"):
        breakdown.append(f"ソフトウェア {_yen(f['sw_revenue'])}")
    if f.get("service_revenue"):
        breakdown.append(f"サービス {_yen(f['service_revenue'])}")
    if breakdown:
        roi_bullets.append("内訳: " + " / ".join(breakdown))
    for c in ctx.comparables:
        roi_bullets.append(
            f"参考事例: {c['customer']}（{c['product_category']}）{_yen(c['amount'])}・{c['outcome']}")
    roi_bullets.append("次のステップ: 詳細お見積のご提示と導入スケジュールのすり合わせ")
    roi_slide = {
        "layout": "content",
        "title": "投資対効果と次のステップ",
        "bullets": roi_bullets,
        "notes": "金額はすべてSPRの実データ。参考事例は類似案件から取得（創作なし）。",
    }

    return {"slides": [title_slide, challenge_slide, solution_slide, roi_slide]}


def generate(deal_id: str, lang: str = "ja") -> tuple[Path, DocumentContext] | None:
    """Build + render a proposal for `deal_id`. Returns (path, context) or None."""
    ctx = build_document_context(deal_id)
    if ctx is None:
        return None
    spec = build_proposal_spec(ctx, lang=lang)
    path = output_path("proposal", deal_id, "pptx")
    render_pptx(spec, path)
    return path, ctx


if __name__ == "__main__":
    import sys

    did = sys.argv[1] if len(sys.argv) > 1 else "D001"
    out = generate(did)
    if out is None:
        print(f"deal {did} not found")
    else:
        p, c = out
        print(f"wrote {p}  ({p.stat().st_size} bytes) for {c.customer}")
