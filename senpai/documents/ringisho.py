"""generate_ringisho — a formal Japanese internal-approval document (稟議書), DOCX.

Written from the *customer's IT-manager persona pitching their own CEO*: it uses our
deal's real financials to justify solving the pain points logged in the SPR. The
numbers are injected from context.py (never invented); the justification prose comes
from narrative.ringisho_prose (LLM if available, templated fallback). Renders via render.py.

Smoke:  python -m senpai.documents.ringisho D001
"""
from __future__ import annotations

from pathlib import Path

from senpai.documents import narrative
from senpai.documents.context import DocumentContext, build_document_context
from senpai.documents.render import output_path, render_docx


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return "¥0"


def build_ringisho_spec(ctx: DocumentContext) -> dict:
    """Build the 稟議書 doc spec from a grounded DocumentContext."""
    prose = narrative.ringisho_prose(ctx)
    f = ctx.financials
    invest = _yen(f.get("investment", 0))

    # Grounded financial table lines (numbers from SPR, not prose).
    effect_body = [prose["effect"], "", "■ 投資内訳"]
    effect_body.append(f"- 投資総額: {invest}")
    if f.get("hw_revenue"):
        effect_body.append(f"- ハードウェア: {_yen(f['hw_revenue'])}")
    if f.get("sw_revenue"):
        effect_body.append(f"- ソフトウェア: {_yen(f['sw_revenue'])}")
    if f.get("service_revenue"):
        effect_body.append(f"- サービス・保守: {_yen(f['service_revenue'])}")
    for c in ctx.comparables:
        effect_body.append(f"- 参考(同業他社): {c['customer']} {_yen(c['amount'])}・{c['outcome']}")

    products = "、".join(p["name"] for p in ctx.products[:4]) or ctx.product_category
    subject = f"件名: {ctx.product_category}導入に関する設備投資の承認について"

    sections = [
        {"heading": "稟議書", "body": [
            f"起案日: {ctx.today}",
            f"起案部門: 情報システム部（{ctx.customer}）",
            subject,
        ]},
        {"heading": "1. 背景・課題", "body": [prose["background"]]},
        {"heading": "2. 提案内容", "body": [
            prose["proposal"],
            f"調達先: 大塚商会 / 対象: {products}（{ctx.product_category}）",
        ]},
        {"heading": "3. 投資額と効果", "body": effect_body},
        {"heading": "4. 結論・承認依頼", "body": [prose["conclusion"]]},
        {"heading": "承認欄", "body": ["社長　　　部門長　　　起案者"]},
    ]
    return {"title": "稟議書", "subtitle": f"{ctx.customer}　情報システム部", "sections": sections}


def generate(deal_id: str) -> tuple[Path, DocumentContext] | None:
    """Build + render a 稟議書 for `deal_id`. Returns (path, context) or None."""
    ctx = build_document_context(deal_id)
    if ctx is None:
        return None
    spec = build_ringisho_spec(ctx)
    path = output_path("ringisho", deal_id, "docx")
    render_docx(spec, path)
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
