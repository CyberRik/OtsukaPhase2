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

    slides = [title_slide]

    # Slide (multi-deal only) — 対象案件一覧: which deals this deck merges, so a
    # "cover all of their deals" proposal never leaves the rep guessing which
    # deals fed the numbers on the slides that follow.
    if len(ctx.deals) > 1:
        deal_lines = [f"{x['deal_id']} {x['deal_name']}（{x['product_category']}）"
                      f"— {_yen(x['amount'])}・{x['rank']}" for x in ctx.deals]
        slides.append({
            "layout": "content",
            "title": "対象案件一覧",
            "icon": "summary",
            "bullets": deal_lines,
            "notes": f"{len(ctx.deals)}件の案件を統合したご提案です。",
        })

    # Slide 2 (New) — 提案のサマリー
    exec_summary_slide = {
        "layout": "content",
        "title": "提案のサマリー",
        "icon": "summary",
        "bullets": ["本提案の目的と目指す姿", "主要なソリューション", "期待される効果と投資対効果"],
        "notes": "提案の全体像を簡潔に記載。",
    }

    # Slide 3 — 背景・なぜ今
    background_slide = {
        "layout": "content",
        "title": "背景 — なぜ今、取り組むべきか",
        "icon": "background",
        "bullets": prose["why_now"],
        "notes": "業界動向とタイミングの整理（顧客の課題に基づく framing）。",
    }

    # Slide 4 (New) — 現状のIT環境とアセスメント
    env = ctx.environment or {}
    env_bullets = [
        f"業種: {ctx.industry} / 規模: {ctx.size}",
    ]
    if env:
        for k, v in env.items():
            env_bullets.append(f"{k}: {v}")
    else:
        env_bullets.append("現行システムの課題・制約事項")
        
    assessment_slide = {
        "layout": "content",
        "title": "現状のIT環境とアセスメント",
        "icon": "assessment",
        "bullets": env_bullets,
        "notes": "SPR/顧客マスタに登録されているIT環境や規模に基づく現状認識。",
    }

    # Slide 5 — 課題（framing 済み、but grounded in the real pain points）
    challenge_slide = {
        "layout": "content",
        "title": "課題 — 現状のお困りごと",
        "icon": "challenge",
        "bullets": prose["challenges"],
        "notes": "SPRの日報・customer_challengeから抽出した実際の課題を framing。",
    }

    # Slide 6 — ソリューション（framing + the real catalog products/prices）
    solution_headers = ["製品名", "製品コード", "価格"]
    solution_rows = [[p['name'], p['code'], _yen(p['price'])] for p in ctx.products[:4]]
    
    # We will include the prose benefits in the slide notes so they aren't lost
    sol_notes = "便益は framing、製品・価格は大塚商会カタログの実データ。\n\n[Framing / Benefits]:\n" + "\n".join(prose["solution"])
    
    solution_slide = {
        "layout": "table",
        "title": f"ソリューション — {ctx.product_category}",
        "icon": "solution",
        "table": {
            "headers": solution_headers,
            "rows": solution_rows,
        },
        "notes": sol_notes,
    }

    # Slide 7 — 投資対効果（real numbers + value framing + real comparables）
    f = ctx.financials
    quoted = f.get("quote_amount")
    standard = f.get("standard_amount") or f.get("investment", 0)
    
    chart_categories = []
    chart_values = []
    if quoted and standard and quoted != standard:
        chart_categories = ["標準構成", "ご提案価格"]
        chart_values = [standard, quoted]
    elif quoted:
        chart_categories = ["ご提案価格"]
        chart_values = [quoted]
    else:
        chart_categories = ["投資額"]
        chart_values = [f.get('investment', 0)]
        
    roi_notes = "金額はすべてSPRの実データ。参考事例は同カテゴリの実案件（創作なし）。\n\n[Value / Comparables]:\n"
    roi_notes += "\n".join(prose["value"]) + "\n"
    for c in ctx.comparables:
        roi_notes += f"参考事例: {c['customer']}（{c['product_category']}）{_yen(c['amount'])}・{c['outcome']}\n"

    roi_slide = {
        "layout": "chart",
        "title": "投資対効果",
        "icon": "roi",
        "chart": {
            "renderer": "mpl",
            "categories": chart_categories,
            "series": [{"name": "Amount", "values": chart_values}]
        },
        "notes": roi_notes.strip(),
    }

    # Slide 7b (quote-only) — 割引率 as a doughnut: a real, quoted discount is a
    # customer-appropriate number to visualize (unlike an internal health score,
    # which has no place in a customer-facing deck).
    discount_slide = None
    disc = f.get("discount_rate")
    if quoted and standard and quoted != standard and disc:
        discount_slide = {
            "layout": "chart",
            "title": "標準価格からの割引率",
            "icon": "roi",
            "chart": {
                "type": "doughnut",
                "categories": ["割引額", "ご提案価格"],
                "series": [{"name": "構成比", "values": [disc, max(0, 100 - disc)]}],
            },
            "notes": f"標準 {_yen(standard)} → ご提案 {_yen(quoted)}（{disc}%割引）。SPRの見積実データ。",
        }

    # Slide 8 (New) — 導入スケジュール、接続された工程図として可視化
    schedule_slide = {
        "layout": "timeline",
        "title": "導入スケジュール (標準モデル)",
        "icon": "schedule",
        "phases": [
            {"label": "要件定義", "duration": "0.5〜1ヶ月", "detail": "要件の確認、仕様確定"},
            {"label": "機器手配・設定", "duration": "1〜1.5ヶ月", "detail": "手配・キッティング"},
            {"label": "導入・テスト", "duration": "0.5〜1ヶ月", "detail": "現地設置、動作確認"},
            {"label": "運用開始", "duration": "ー", "detail": "引継ぎ、本番稼働"},
        ],
        "notes": "標準的な導入スケジュール。案件の実態に合わせて調整。",
    }

    # Slide 9 — 次のステップ
    next_slide = {
        "layout": "content",
        "title": "次のステップ",
        "icon": "next",
        "bullets": prose["next_steps"],
        "notes": "丁寧な依頼文体で次の一歩を提示。",
    }

    slides += [exec_summary_slide, background_slide, assessment_slide, challenge_slide,
              solution_slide, roi_slide]
    if discount_slide:
        slides.append(discount_slide)
    slides += [schedule_slide, next_slide]
    return {"slides": slides}


def generate(deal_id: str, lang: str = "ja",
            deal_ids: list[str] | None = None) -> tuple[Path, DocumentContext, dict] | None:
    """Build + render a proposal for `deal_id`. Returns (path, context, spec) or None.
    The spec is returned so the caller can show the exact outline that was rendered
    without re-authoring it (which, with the LLM prose pass, would be a second call
    and could differ from the file). `deal_ids`, when given, merges that customer's
    other deals into the same deck (see context.build_document_context)."""
    ctx = build_document_context(deal_id, deal_ids=deal_ids)
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
