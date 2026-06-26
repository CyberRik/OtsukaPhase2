"""Synthesis-style booster for the decomposed (8B) synthesis path.

Investigation (docs/phase25_session_log.md): the Q4 8B holds grounding/factual
fidelity but writes more mechanically than the 27B — bullet-dumps, repeated
fields, little prioritisation. The role system prompts it inherits were written
for *tool use + grounding*, and even instruct enumeration (「列挙は箇条書きにし」).
This module supplies an explicit **synthesis-style** directive (and optional
few-shot exemplar) injected ONLY when the smaller model writes the answer, to test
whether the remaining gap is a prompting problem rather than a capability one.

Nothing here changes the 27B path. `apply()` is a no-op unless a caller passes a
non-"none" mode (driven by config.SYNTH_STYLE / the bench harness)."""
from __future__ import annotations

# The directive. Targets exactly the regressions observed: enumeration over
# prioritisation, fact-repetition over abstraction, redundancy, flat listing
# without a senior's "read". Grounding clause is repeated so style never licenses
# fabrication.
STYLE_DIRECTIVE = (
    "【合成スタイル（最重要・回答の質）】\n"
    "あなたは経験豊富な先輩営業です。データの再掲ではなく、後輩を導く"
    "『読み』を述べてください。次を厳守すること:\n"
    "- 列挙より優先順位: すべてを並べず、いま最も重要な2〜3点に絞る。"
    "各案件の同じ項目（決裁者・評価軸など）を機械的に繰り返さない。\n"
    "- 抽象化と統合: 個々の事実をそのまま書き写さず、共通点・傾向にまとめてから示す。"
    "重複する情報は一度だけ述べ、差分のみ強調する。\n"
    "- 洞察を加える: 『何が起きているか』だけでなく『なぜ重要か』『だから次に"
    "何をすべきか』まで踏み込む。\n"
    "- 簡潔さ: 冗長な表や繰り返しの箇条書きを避け、短く密度の高い文章にする。"
    "見出しは最小限に。\n"
    "- 具体的な次の一手: 最後に、実行可能で具体的な推奨を2〜3点に絞って述べる。\n"
    "- 事実・数値・出典は与えられた情報のものだけを使い、創作しない。\n"
    "口調: 後輩に寄り添い、要点を絞って導く先輩の語り口。"
)

# One high-quality style exemplar distilled from observed 27B output. The CONTENT
# is illustrative only (generic 顧客A / 案件) — it teaches *shape* (prioritise →
# abstract → why → next step), explicitly flagged so the model never imports its
# facts. A contrastive bad→good pair makes the target unambiguous.
_FEWSHOT_USER = (
    "（スタイル参考用の例。内容は無関係。以下の素材から先輩としての読みを書く）\n"
    "素材: 顧客Aに3案件。いずれも決裁者は情シス部長、評価軸は運用負荷と実績。"
    "1件は接触多数だが役員会待ちで停滞、2件は価格交渉中。直近の日報に『検討します』が頻出。"
)
_FEWSHOT_ASSISTANT = (
    "**状況の読み:** 顧客Aは3案件とも情シス部長が窓口で、判断軸は一貫して"
    "「運用負荷の軽さ」と「実績」です。つまり個別に攻めるより、この2点を満たす"
    "提案を横展開できる相手です。\n\n"
    "気になるのは停滞案件で、接触は多いのに役員会待ち＝担当者は前向きでも"
    "決裁が動いていない典型。日報の『検討します』の多さもこのサインです。"
    "熱量ではなく、決裁を前に進める材料が足りていません。\n\n"
    "**次の一手:**\n"
    "1. 停滞案件は、役員会に出せる1枚（投資対効果と運用削減の実績）を担当者に渡し、"
    "稟議を代わりに通せる状態を作る。\n"
    "2. 価格交渉中の2件は、値引きではなく実績事例で「運用負荷」の不安を消しにいく。"
)


def apply(messages: list[dict], mode: str) -> list[dict]:
    """Return a copy of `messages` with the synthesis-style booster applied.

    mode: "none"    → unchanged (default; 27B path always uses this)
          "style"   → STYLE_DIRECTIVE folded into the system message
          "fewshot" → STYLE_DIRECTIVE + one style exemplar before the real turn
    Safe on any message list (chat convo with tool turns, or a single research
    user message)."""
    if mode == "none" or not messages:
        return messages
    out = [dict(m) for m in messages]
    if out and out[0].get("role") == "system":
        out[0]["content"] = (out[0].get("content") or "") + "\n\n" + STYLE_DIRECTIVE
        insert_at = 1
    else:
        out.insert(0, {"role": "system", "content": STYLE_DIRECTIVE})
        insert_at = 1
    if mode == "fewshot":
        out[insert_at:insert_at] = [
            {"role": "user", "content": _FEWSHOT_USER},
            {"role": "assistant", "content": _FEWSHOT_ASSISTANT},
        ]
    return out
