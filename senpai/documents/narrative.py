"""Grounded persuasive prose for the specialized documents.

The numbers in a proposal / 稟議書 always come from the deterministic context
(context.py) — never from a model. This module only supplies the *qualitative*
framing (value proposition, justification paragraphs). When SENPAI_USE_LLM is on and
the model is reachable, it rephrases the grounded facts persuasively; otherwise a
deterministic templated string is used, so a valid document is always produced
GPU-free (mirrors senpai/llm/narrate.py's fallback philosophy).
"""
from __future__ import annotations

import json
import os
import re

from senpai.documents import playbook
from senpai.documents.context import DocumentContext


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model response (handles code fences)."""
    if not text:
        return None
    t = re.sub(r"```(?:json)?", "", text).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


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


# --- proposal deck prose --------------------------------------------------------
def _clean_bullets(items, limit: int) -> list[str]:
    out: list[str] = []
    for it in items or []:
        s = str(it).strip().lstrip("・-•").strip()
        if s:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _templated_prose(ctx: DocumentContext, pains: list[str]) -> dict:
    """Grounded, GPU-free framing for the proposal deck. Better than raw field-dumps
    even without the model: each pain is tied to its business impact, and the arc
    (why-now → challenges → solution → value → next steps) is preserved."""
    cat = ctx.product_category or "本領域"
    return {
        "catch": f"{ctx.customer}様の「{'、'.join(pains[:3])}」を、{cat}で解決するご提案",
        "why_now": [
            f"{ctx.industry or '同業界'}では業務のデジタル化と省力化が加速しています",
            "対応の遅れは生産性・コスト面での機会損失につながります",
            "今こそ、確実な実績のある構成で着実に前進すべきタイミングです",
        ],
        "challenges": [f"{p} — 業務効率・コスト・リスクへの影響" for p in pains[:5]],
        "solution": [
            f"{cat}を軸に、上記の課題へ一対一で対応します",
            "大塚商会の導入実績と保守体制により、確実な導入・運用を実現します",
        ],
        "value": [
            "投資に見合う業務改善・省力化の効果が見込めます",
            "同規模・同業の導入実績に照らし、妥当な投資水準です",
        ],
        "next_steps": [
            "詳細お見積のご提示",
            "導入スケジュールのすり合わせ",
            "ご要望に応じた小規模スタート・検証も可能です",
        ],
    }


def proposal_prose(ctx: DocumentContext, lang: str = "ja") -> dict:
    """One grounded pass of persuasive framing for the proposal deck, following
    Otsuka's arc. Returns a title catch + bullet lists for the qualitative slides.
    NUMBERS / product prices / comparables are NOT here — they stay deterministic in
    proposal.py; this supplies only prose, so nothing is invented. Templated fallback
    when the model is off, so a grounded deck is always produced GPU-free."""
    pains = ctx.pain_points[:5] or ["現行業務の課題"]
    base = _templated_prose(ctx, pains)
    if not _use_llm():
        return base
    prods = "、".join(p["name"] for p in ctx.products[:5]) or ctx.product_category
    prompt = (
        "あなたは大塚商会のトップ営業提案ライターです。以下の事実だけを用いて、提案書"
        "(スライド)の各セクションの箇条書きを作成し、STRICT JSONのみで出力してください"
        "(前置き・コードフェンス不可)。スキーマ:\n"
        '{"catch": str, "why_now": [str], "challenges": [str], '
        '"solution": [str], "value": [str], "next_steps": [str]}\n'
        "- catch: 表紙の価値提案1文(20〜40字、顧客が得る成果で表現)。\n"
        "- why_now: 『なぜ今か』の背景を3点(業界動向・タイミング)。\n"
        "- challenges: 提示された課題を、それぞれ業務・コスト・リスクへの影響を一言添えて"
        "言い換える(新たな課題を創作しない)。\n"
        "- solution: 提供領域/製品が各課題にどう効くかを便益ベースで2〜3点。\n"
        "- value: 投資対効果の説得材料を2〜3点(具体的な金額は書かない/別途記載)。\n"
        "- next_steps: 次の一歩を丁寧な依頼文体で2〜3点。\n"
        "新しい数値・固有名詞・製品を創作しないこと。各項目は短い体言止めで。\n"
        f"{playbook.proposal_style_guide()}\n"
        f"顧客: {ctx.customer}（{ctx.industry}/{ctx.size}）\n"
        f"提供領域: {ctx.product_category}\n"
        f"想定製品: {prods}\n"
        f"課題: {'、'.join(pains)}\n")
    obj = _extract_json(_complete(prompt) or "")
    if not obj:
        return base
    # Merge over the templated base so any missing/empty field stays grounded.
    catch = str(obj.get("catch") or "").strip().splitlines()[0:1]
    return {
        "catch": (catch[0] if catch else base["catch"]),
        "why_now": _clean_bullets(obj.get("why_now"), 4) or base["why_now"],
        "challenges": _clean_bullets(obj.get("challenges"), 5) or base["challenges"],
        "solution": _clean_bullets(obj.get("solution"), 3) or base["solution"],
        "value": _clean_bullets(obj.get("value"), 3) or base["value"],
        "next_steps": _clean_bullets(obj.get("next_steps"), 3) or base["next_steps"],
    }


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
