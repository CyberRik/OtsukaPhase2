"""Otsuka proposal playbook — the narrative DNA extracted from Otsuka's own deck.

Derived from the 34-slide sales proposal in senpai/data/templates/otsuka_source.pptx
(the same deck the brand template — render.py's base — was stripped from). That deck
follows a textbook Japanese B2B persuasion arc; we capture it here so generated
documents match Otsuka's *content* style, not just the look.

Two kinds of artifact live here, and both are prompt material — edit them here and
every caller picks up the change:
  • PROPOSAL_ARC      — the section-by-section flow a grounded proposal should follow.
  • *_style_guide()   — compact instruction blocks + few-shot examples injected into
                        the LLM prompts in narrative.py (grounded proposal / 稟議書)
                        and author.py (freeform decks).

Nothing here invents facts: the style guides explicitly forbid fabricating figures,
mirroring the grounding rules already enforced in narrative.py / author.py.
"""
from __future__ import annotations

# The rhetorical arc, section by section. `goal` is what that section must achieve;
# this is the outline build_proposal_spec should grow toward (today it covers the
# 課題 / ソリューション / 根拠 core). Kept as data so it doubles as documentation.
PROPOSAL_ARC: list[dict[str, str]] = [
    {"section": "表紙",
     "goal": "「{顧客}御中」と作成者・日付。見出しは製品名ではなく“顧客が得る成果”で表現する。"},
    {"section": "背景・なぜ今",
     "goal": "業界トレンド・技術更新・規制などマクロな変化を示し、『今動く理由』を作る。"},
    {"section": "課題・共感",
     "goal": "現場で実際に起きている困りごとを具体的に挙げ、生産性低下やストレス等の感情面にも触れて共感を得る。"},
    {"section": "ソリューション",
     "goal": "課題に一対一で対応する提供内容。製品・プランのラインアップを明示する。"},
    {"section": "根拠・効果",
     "goal": "自社検証データや実数値で効果を裏づける。数値には必ず『※あくまで目安』等の注記を添える。"},
    {"section": "導入・安心",
     "goal": "アセスメント等のスモールスタート、サポート体制、会社概要・実績で導入不安を下げる。"},
    {"section": "次のアクション",
     "goal": "見積提示・スケジュール調整など具体的な次の一歩を、丁寧な依頼文体で提示する。"},
]

# The voice, distilled from the source deck. Topic-agnostic enough to steer any
# Otsuka-authored material.
STYLE_PRINCIPLES: list[str] = [
    "見出し・キャッチは製品名ではなく『顧客が得る成果』で書く（例:「生産性を高める高速10ギガ回線」）。",
    "解決策の前にまず課題と『なぜ今か』を提示し、共感を作ってから提案へ進む。",
    "効果は具体的な数値で示し、根拠（検証環境など）と『※あくまで目安』の注記を必ず添える。",
    "1スライド1メッセージ。要点は短い体言止め・箇条書きで。",
    "出典・前提のない数値や固有名詞を創作しない。",
    "結びは押し付けず、次の一歩を丁寧な依頼文体で示す。",
]


def _principles_block() -> str:
    return "\n".join(f"- {p}" for p in STYLE_PRINCIPLES)


def arc_outline_text() -> str:
    """Human-readable arc — for docs / the freeform deck author's structural hint."""
    return "\n".join(f"{i}. 【{s['section']}】{s['goal']}"
                     for i, s in enumerate(PROPOSAL_ARC, 1))


def proposal_style_guide() -> str:
    """Style block for the grounded proposal / 稟議書 prompts (narrative.py).

    A short instruction list plus one few-shot headline example, so the model adopts
    Otsuka's benefit-led, problem-first voice without copying the source deck's topic.
    """
    return (
        "【大塚商会の提案スタイル】次の原則に従って書くこと:\n"
        f"{_principles_block()}\n"
        "（表紙キャッチの例:「生産性を高める高速10ギガ回線」「業務を止めないクラウドバックアップ」）"
    )


def deck_style_guide() -> str:
    """Style block for the freeform deck author (author.py).

    Same craft principles plus the section arc as a suggested skeleton, so business
    decks flow problem→solution→evidence→action. Topic stays whatever the user asked.
    """
    return (
        "【構成・文体の指針(大塚商会スタイル)】\n"
        f"{_principles_block()}\n"
        "提案・営業系の内容では概ね次の流れを意識する（話題に合わせて取捨選択してよい）:\n"
        f"{arc_outline_text()}"
    )
