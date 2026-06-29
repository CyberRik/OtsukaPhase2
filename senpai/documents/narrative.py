"""Grounded persuasive prose for the specialized documents.

The numbers in a proposal / 稟議書 always come from the deterministic context
(context.py) — never from a model. This module only supplies the *qualitative*
framing (value proposition, justification paragraphs). When SENPAI_USE_LLM is on and
the model is reachable, it rephrases the grounded facts persuasively; otherwise a
deterministic templated string is used, so a valid document is always produced
GPU-free (mirrors senpai/llm/narrate.py's fallback philosophy).
"""
from __future__ import annotations

import os

from senpai.documents import playbook
from senpai.documents.context import DocumentContext


def _use_llm() -> bool:
    return os.environ.get("SENPAI_USE_LLM", "0").lower() not in ("0", "false", "", "no")


def _complete(prompt: str) -> str | None:
    """One grounded completion, pinned to the primary endpoint. None on any failure
    so the caller falls back to the templated string."""
    try:
        from senpai.llm.client import simple_complete
        out = simple_complete([{"role": "user", "content": prompt}],
                              temperature=0.4, no_think=True, allow_fallback=False)
        return out.strip() or None
    except Exception:  # noqa: BLE001 — model down/timeout → templated fallback
        return None


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return "¥0"


# --- proposal -------------------------------------------------------------------
def proposal_value_prop(ctx: DocumentContext, lang: str = "ja") -> str:
    """A short value proposition for the title slide. Grounded, never numeric-inventing."""
    pains = "、".join(ctx.pain_points[:3]) or "業務課題"
    if _use_llm():
        prompt = (
            "あなたは大塚商会の営業提案ライターです。以下の事実だけを使い、"
            "提案書の表紙に載せる1文の価値提案(キャッチコピー)を日本語で書いてください。"
            "新しい数値や事実を創作しないこと。1文のみ、20〜40字程度。\n"
            f"{playbook.proposal_style_guide()}\n"
            f"顧客: {ctx.customer}（{ctx.industry}/{ctx.size}）\n"
            f"主要課題: {pains}\n"
            f"提供領域: {ctx.product_category}\n")
        if (out := _complete(prompt)):
            return out.splitlines()[0].strip()
    return f"{ctx.customer}様の「{pains}」を、{ctx.product_category}で解決するご提案"


# --- ringisho -------------------------------------------------------------------
def ringisho_prose(ctx: DocumentContext) -> dict:
    """Return {'background','proposal','effect','conclusion'} paragraphs for the 稟議書,
    written from the customer's IT-manager persona pitching their CEO. Numbers are
    injected by ringisho.py from ctx; here we supply the justification prose."""
    pains = "、".join(ctx.pain_points[:3]) or "現行システムの課題"
    prods = "、".join(p["name"] for p in ctx.products[:3]) or ctx.product_category
    invest = _yen(ctx.financials.get("investment", 0))

    if _use_llm():
        prompt = (
            "あなたは『顧客企業の情報システム部門の責任者』です。自社の社長(CEO)に対し、"
            "下記の設備投資の承認を求める『稟議書』の本文を、丁寧かつ説得力のある日本語の"
            "ビジネス文体で書いてください。提示された事実・数値のみを用い、創作しないこと。"
            "次の4つの見出しごとに、それぞれ2〜4文の段落で出力してください: "
            "【背景・課題】【提案内容】【投資額と効果】【結論・承認依頼】。\n"
            f"{playbook.proposal_style_guide()}\n"
            f"自社: {ctx.customer}（{ctx.industry}/{ctx.size}）\n"
            f"課題: {pains}\n"
            f"導入予定（大塚商会より調達）: {prods}（{ctx.product_category}）\n"
            f"投資額: {invest}\n")
        out = _complete(prompt)
        if out:
            return _split_ringisho(out, ctx, invest, pains, prods)

    return _templated_ringisho(ctx, invest, pains, prods)


def _templated_ringisho(ctx: DocumentContext, invest: str, pains: str, prods: str) -> dict:
    return {
        "background": (
            f"当社（{ctx.customer}・{ctx.industry}）では、現在「{pains}」が顕在化しており、"
            "業務効率および競争力の維持に影響を及ぼしております。早期の対応が必要と判断いたします。"),
        "proposal": (
            f"上記課題への対応として、大塚商会より{prods}（{ctx.product_category}）の導入を提案いたします。"
            "同社の実績と保守体制を踏まえ、確実な導入と運用が見込めます。"),
        "effect": (
            f"本件の投資額は{invest}を見込んでおります。課題解決による業務改善効果に加え、"
            "同規模・同業の導入事例においても妥当な投資水準であり、費用対効果は十分と考えます。"),
        "conclusion": (
            f"以上より、{invest}の投資について承認賜りたく、ここに稟議申し上げます。"
            "ご審議のほど、よろしくお願い申し上げます。"),
    }


def _split_ringisho(text: str, ctx: DocumentContext, invest: str, pains: str, prods: str) -> dict:
    """Best-effort split of an LLM 稟議書 body by its 4 headings; fall back per-section."""
    base = _templated_ringisho(ctx, invest, pains, prods)
    keys = [("background", "背景"), ("proposal", "提案"),
            ("effect", "投資"), ("conclusion", "結論")]
    for i, (k, marker) in enumerate(keys):
        start = text.find(marker)
        if start == -1:
            continue
        nxt = len(text)
        for _, m2 in keys[i + 1:]:
            j = text.find(m2, start + 1)
            if j != -1:
                nxt = min(nxt, j)
        chunk = text[start:nxt]
        # drop the heading line itself
        body = chunk.split("】", 1)[-1].split("\n", 1)[-1] if "】" in chunk else chunk
        body = body.strip().strip("【】 \n")
        if body:
            base[k] = body
    return base
