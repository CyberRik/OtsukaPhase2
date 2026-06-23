"""Sales Review Coach engine — make a senior rep's reasoning explicit.

Given a junior's free-text note (and, optionally, the structured deal it relates
to), produce six teaching outputs:

  1. observations     — what an experienced rep would notice
  2. missing_info     — information that isn't there but should be
  3. risks            — risk signals
  4. questions        — what a senior would ask next
  5. next_actions     — *several* plausible moves (never one 'right answer')
  6. decision_factors — what should influence the choice

The core is deterministic: a set of LENSES encodes a senior's mental checklist.
Each lens fires when its cue phrases are ABSENT from the note (the gap a junior
tends not to see). Presence-based detectors (stall language, competitor) add
risks and factors. When a `deal_id` is supplied, the existing scoring/flags
engine is fused in so structured signals reinforce the text reading.

`retrieve_playbook` surfaces attributed senior advice as *options* to consider.
`narrate_review` lets exp3 rephrase the SAME findings; it falls back to the
deterministic text when the model server is down — so the coach never invents an
answer and never breaks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from senpai import config
from senpai.coach.explainability import build_review_explanations
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Lens:
    """One dimension of a senior rep's checklist. Fires when none of `cues`
    appear in the note — i.e. the dimension was left unaddressed."""
    name: str
    cues: list[str]
    observation: str
    missing: str
    question: str
    risk: str
    factor: str
    tags: list[str] = field(default_factory=list)


@dataclass
class CoachReview:
    observations: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    decision_factors: list[str] = field(default_factory=list)
    used_deal: bool = False
    explanations: list = field(default_factory=list)  # list[Explanation]
    # Grounding P0: absence-derived gaps as bilingual OPEN QUESTIONS (never facts).
    # A note merely omitting "決裁者" yields a question to ask, not a claim that the
    # decision-maker is unknown. Consumed by the Senior Commentary prompt.
    open_questions: list[dict] = field(default_factory=list)  # [{"ja":..,"en":..}]


# English phrasings for each absence lens' open question (the lens question text
# itself is authored in Japanese). Keyed by Lens.name so English commentary never
# has to paste a raw Japanese question string.
_LENS_QUESTION_EN: dict[str, str] = {
    "decision_maker": "Has the decision-maker been identified, and is anyone else involved in the decision?",
    "timeline": "When does the customer expect to decide, and is the next contact date set?",
    "criteria": "What criteria will the customer use to evaluate options (price / support / track record)?",
    "next_step": "What is the agreed next step, and who owns it?",
    "budget": "Is a budget confirmed, and what is its scale?",
}
_COMPETITION_Q = {
    "ja": "他社と比較されていますか？どこと、どの点で比べられていますか？",
    "en": "Are competitors being compared, and if so against whom and on what points?",
}


# ---------------------------------------------------------------------------
# The senior's checklist — absence-based lenses
# ---------------------------------------------------------------------------
LENSES: list[Lens] = [
    Lens(
        name="decision_maker",
        cues=["決裁", "決裁者", "決定権", "社長", "部長", "役員", "意思決定", "決める方", "稟議"],
        observation="誰が最終的に決めるのか(決裁者)が見えていない",
        missing="決裁者・意思決定に関わる人",
        question="この件はどなたが最終的にご決定されますか？他に関わる方はいますか？",
        risk="決裁ルートが不明なまま進むと、終盤で想定外の関与者が出て止まりやすい",
        factor="決裁者が誰で、何を重視するか(コスト/安心/現場負担)",
        tags=["決裁者未特定", "稟議"],
    ),
    Lens(
        name="timeline",
        cues=["次回", "日程", "期限", "までに", "来週", "来月", "月末", "予定日",
              "スケジュール", "いつ", "日に", "時頃"],
        observation="次の打ち合わせや意思決定の時期が決まっていない",
        missing="次回接触日・意思決定の時期",
        question="社内でのご検討はいつ頃まとまりそうですか？次にお話しする日を今決めておけますか？",
        risk="期日がないと『検討します』のまま自然消滅しやすい",
        factor="顧客の導入希望時期と予算サイクル(年度末など)",
        tags=["決定先延ばし", "クロージング"],
    ),
    Lens(
        name="criteria",
        cues=["基準", "比較", "重視", "条件", "決め手", "要件", "ポイント", "評価"],
        observation="何を基準に判断されるのかが分かっていない",
        missing="意思決定の判断基準",
        question="ご判断にあたって特に重視される点はどこですか？(価格/サポート/実績 など)",
        risk="判断基準が不明だと、的を外した提案を続けてしまう",
        factor="顧客が重視する価値(価格 vs 安心 vs 実績)",
        tags=["差別化", "提案"],
    ),
    Lens(
        name="next_step",
        cues=["次回", "再訪", "お打ち合わせ", "宿題", "持ち帰り", "送付", "提出", "ご提案",
              "デモ", "見積"],
        observation="次の具体的な一歩(誰が・何を)が決まっていない",
        missing="次の具体的アクションと担当",
        question="次は私たちから何をお持ちすればよいですか？こちらの宿題を一つ決めませんか？",
        risk="ボールの所在が曖昧だと案件が宙に浮く",
        factor="こちらが主導権を保てる次の一手があるか",
        tags=["クロージング", "提案"],
    ),
    Lens(
        name="budget",
        cues=["予算", "金額", "価格", "費用", "コスト", "見積", "万円", "円"],
        observation="予算の有無・規模が確認できていない",
        missing="予算の所在と規模",
        question="今回のご予算感や、予算の確保状況は伺えますか？",
        risk="予算未確認のまま提案すると、後で金額が理由で破談になりやすい",
        factor="予算が確保済みか、これから稟議か",
        tags=["予算", "価格"],
    ),
]


def _present(text: str, cues: list[str]) -> bool:
    return any(c in text for c in cues)


def _dedup(items: list[str]) -> list[str]:
    """Order-preserving de-dup (lenses + structured signals can overlap)."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
def review_note(note: str, deal: dict | None = None,
                notes: list[dict] | None = None, report: dict | None = None,
                today: date | None = None) -> CoachReview:
    """Coach a free-text note. `deal`/`notes`/`report` are optional structured
    context (when the note relates to a known deal) and only ever *reinforce* the
    text reading — the coach works on text alone."""
    text = (note or "").strip()
    today = today or config.today()
    r = CoachReview(used_deal=deal is not None)
    fired_tags: list[str] = []
    fired_lenses: list[dict] = []   # structured lens data for explainability

    # --- absence lenses: the senior's checklist of unasked questions ---------
    for lens in LENSES:
        if not _present(text, lens.cues):
            r.observations.append(lens.observation)
            r.missing_info.append(lens.missing)
            r.questions.append(lens.question)
            r.risks.append(lens.risk)
            r.decision_factors.append(lens.factor)
            r.open_questions.append({"ja": lens.question,
                                     "en": _LENS_QUESTION_EN.get(lens.name, lens.question)})
            fired_tags.extend(lens.tags)
            fired_lenses.append({
                "name": lens.name, "cues": lens.cues,
                "tags": lens.tags, "observation": lens.observation,
            })

    # --- presence detectors -------------------------------------------------
    stall_hit = next((w for w in config.STALL_LEXICON if w in text), None)
    if stall_hit:
        r.observations.append(f"停滞を示す言葉「{stall_hit}」が出ている")
        r.risks.append("顧客の言葉に停滞サインがある。受け身で待つと流れやすい")
        fired_tags.append("決定先延ばし")

    comp_hit = next((w for w in config.COMPETITION_LEXICON if w in text), None)
    if comp_hit:
        r.observations.append(f"競合の存在を示す言葉「{comp_hit}」がある")
        r.questions.append("他社さんと比較されていますか？どこと、どの点で比べられていますか？")
        r.open_questions.append(dict(_COMPETITION_Q))
        r.decision_factors.append("競合がいる → 価格以外の差別化軸(保守・実績)が要る")
        fired_tags.append("競合")

    # --- fuse structured signals when a real deal is supplied ---------------
    fired_signals = []
    fired_flags = []
    if deal is not None:
        res = score_deal(deal, notes or [], today=today)
        fired_signals = list(res.signals)
        for reason in res.top_reasons(3):
            r.observations.append(f"案件データ上のサイン: {reason}")
            r.risks.append(reason)
        fired_flags = deal_flags(deal, notes or [], res.band, today=today)
        for fl in fired_flags:
            r.missing_info.append(fl.message)
        r.decision_factors.append(f"現在の段階: {deal.get('stage', '-')}(健全度 {res.band})")

    # --- next actions: SEVERAL conditional moves, never one answer ----------
    r.next_actions = _next_actions(text, fired_tags)

    # --- senior advice as options to consider (attributed) ------------------
    r.next_actions += _playbook_options(text, fired_tags)

    # de-dup every list
    for fld in ("observations", "missing_info", "risks", "questions",
                "next_actions", "decision_factors"):
        setattr(r, fld, _dedup(getattr(r, fld)))

    # --- build explanations -------------------------------------------------
    r.explanations = build_review_explanations(
        note=text,
        fired_lenses=fired_lenses,
        fired_signals=fired_signals,
        fired_flags=fired_flags,
        stall_hit=stall_hit,
        comp_hit=comp_hit,
        deal=deal,
        activities=notes,
        today=today,
    )

    return r


def _next_actions(text: str, fired_tags: list[str]) -> list[str]:
    """Build a handful of *conditional* moves from which gaps fired. Framed as
    options — the right one depends on context the junior must read."""
    tags = set(fired_tags)
    actions: list[str] = []
    if {"決定先延ばし", "クロージング"} & tags:
        actions.append("その場で次回の打ち合わせ日を仮押さえし、案件を宙に浮かせない")
    if {"決裁者未特定", "稟議"} & tags:
        actions.append("現場担当に『最終決定はどなたと進めますか』と決裁プロセスを確認する")
    if "差別化" in tags:
        actions.append("判断基準をヒアリングしてから、刺さる比較軸で再提案する")
    if {"予算", "価格"} & tags:
        actions.append("予算の確保状況を確認し、決裁者向けの費用対効果1枚を用意する")
    if "競合" in tags:
        actions.append("価格勝負を避け、保守体制・導入後サポートで違いを示す")
    if not actions:
        actions.append("現状で大きな抜けは見当たらない。次の一歩を予定どおり進める")
    return actions


def _playbook_options(text: str, fired_tags: list[str]) -> list[str]:
    """Surface up to 2 senior 'drawer' options — drawn ONLY from human-approved,
    interview-traceable knowledge items (senpai.knowledge). Each option carries
    its source interview + confidence, so nothing here is unsupported advice. If
    no validated item matches, we add nothing (no synthetic filler)."""
    from senpai.knowledge import store as kstore
    hits = kstore.approved_items(tags=list(dict.fromkeys(fired_tags)), query=text)[:2]
    out = []
    for it in hits:
        p = kstore.get_principle(it.provenance.principle_id)
        conf = it.confidence(p)
        src = "・".join(it.provenance.interview_ids) or "—"
        tip = (it.questions or it.signals or [it.scenario])[0]
        out.append(f"先輩の知見(出典 {src} / 確度{conf}): {tip}")
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
_SECTIONS = [
    ("observations",     "🔎 経験豊富な営業が気づくこと"),
    ("missing_info",     "❓ 確認できていない情報"),
    ("risks",            "⚠️ リスクの兆候"),
    ("questions",        "💬 次に聞くとよい質問"),
    ("next_actions",     "➡️ 取りうる次の一手（状況により選ぶ）"),
    ("decision_factors", "⚖️ 判断に影響する要因"),
]

_TEACH_NOTE = ("※ 正解を一つ示すものではありません。先輩なら何に注目するか、"
               "その思考の型を提示します。状況に応じて自分で選んでください。")


def format_review(r: CoachReview) -> str:
    """Deterministic rendering — always available, no model server needed."""
    blocks = [_TEACH_NOTE]
    for field_name, title in _SECTIONS:
        items = getattr(r, field_name)
        if not items:
            continue
        body = "\n".join(f"- {it}" for it in items)
        blocks.append(f"\n{title}\n{body}")
    return "\n".join(blocks)


def narration_prompt(r: CoachReview) -> str:
    """The exact prompt used to ask the model to rephrase the SAME findings.
    Extracted so streaming and non-streaming paths share one source of truth —
    the coaching content is identical either way."""
    def _bul(items: list[str]) -> str:
        return "、".join(items) if items else "なし"

    return (
        "あなたは新人営業を育てる先輩です。以下の分析結果を、教えるトーンで"
        "整理し直してください。守るべきルール: (1)与えられた点だけを使い、"
        "新しい事実や数字を足さない (2)『正解は一つ』にせず、複数の選択肢として"
        "示す (3)見出しは『気づくこと/不足情報/リスク/聞くべき質問/取りうる一手/"
        "判断要因』の6つ。\n"
        f"気づくこと: {_bul(r.observations)}\n"
        f"不足情報: {_bul(r.missing_info)}\n"
        f"リスク: {_bul(r.risks)}\n"
        f"質問: {_bul(r.questions)}\n"
        f"取りうる一手: {_bul(r.next_actions)}\n"
        f"判断要因: {_bul(r.decision_factors)}\n"
    )


def narration_prompt_en(r: CoachReview) -> str:
    """English-mode narration prompt. Same findings as `narration_prompt`, only
    the output language/headings change — a presentation concern, not coaching
    logic. The model re-frames the identical points in English; it must not add
    facts or pick one answer."""
    def _bul(items: list[str]) -> str:
        return "; ".join(items) if items else "none"

    return (
        "You are a senior sales mentor coaching a junior rep. Re-frame the "
        "analysis below in a teaching tone, in natural English. Rules: (1) use "
        "ONLY the points given; add no new facts or numbers (2) never present a "
        "single 'right answer' — offer them as several options (3) keep these six "
        "headings: What a senior notices / Missing information / Risk signals / "
        "Questions to ask / Possible next moves / Decision factors.\n"
        f"What a senior notices: {_bul(r.observations)}\n"
        f"Missing information: {_bul(r.missing_info)}\n"
        f"Risk signals: {_bul(r.risks)}\n"
        f"Questions to ask: {_bul(r.questions)}\n"
        f"Possible next moves: {_bul(r.next_actions)}\n"
        f"Decision factors: {_bul(r.decision_factors)}\n"
    )


def commentary_prompt(note: str, r: CoachReview, context_text: str,
                      has_context: bool, lang: str = "ja",
                      customer_name: str | None = None,
                      deal_id: str | None = None) -> str:
    """Senior Commentary prompt — grounded, three-section, never speculative.

    Grounding P0 structure: the model may state only what the records support
    (Known Facts), turn every information gap into an Open Question (never a
    customer-fact claim), and derive Preparation Suggestions from those two. It is
    forbidden to infer hidden motivations / politics / stakeholder behaviour /
    budget talk, to name any other customer or deal, or to invent examples. When a
    fact is absent it asks; it does not narrate."""
    # Absence-derived gaps are fed as QUESTIONS, never as asserted observations.
    qs = [q.get(lang, q.get("ja", "")) for q in r.open_questions]
    sep = "; " if lang == "en" else "／"
    open_qs = sep.join(dict.fromkeys(q for q in qs if q)) or (
        "none" if lang == "en" else "なし")
    cn = customer_name or ("the current customer" if lang == "en" else "本顧客")
    did = deal_id or ("the current deal" if lang == "en" else "本案件")

    if lang == "en":
        return (
            "You are an experienced sales manager helping a junior rep PREPARE for "
            "this account. Grounding is the priority: state only what the records "
            "support, and turn anything missing into a question — never a claim.\n\n"
            "Write under exactly these three headings, in natural English:\n\n"
            "### Known Facts\n"
            "Only facts directly stated in CONTEXT (CRM, activity, notes, quotes, "
            "orders, account context, deterministic signals). Quote numbers exactly "
            "as written (days inactive, rank age, rank, amount, dates). Do NOT add, "
            "infer, or summarise new facts. If CONTEXT says no customer was found, "
            "list only what the note itself states.\n"
            "Format each fact as a bullet that begins with a short **bold label**, "
            "then the fact as a clear sentence — e.g. `- **Deal Details:** D065 …`. "
            "Group related facts under sensible labels (Customer, Deal Details, "
            "Timeline, Status, Activity, History); write prose, do not just copy the "
            "raw field names. The wording is yours; the facts stay exactly as given.\n\n"
            "### Open Questions\n"
            "Phrase every information gap as a question to ask — never as a fact. "
            "Include these unanswered points as questions: " + open_qs + "\n\n"
            "### Preparation Suggestions\n"
            "1–3 concrete things to prepare before the meeting, derived only from "
            "the Known Facts and Open Questions. You may cite a principle id (e.g. "
            "P001) ONLY if it appears in RELEVANT CORPUS KNOWLEDGE below.\n\n"
            "RULES (strict):\n"
            "- Never infer hidden customer motivations, internal politics, "
            "stakeholder behaviour, or budget discussions.\n"
            "- If the records do not support a statement, move it to Open Questions "
            "— do not assert it and do not build a narrative.\n"
            f"- Never name any customer other than {cn}. Never cite any deal other "
            f"than {did}.\n"
            "- Never reference another customer as an example and never invent "
            "examples or unnamed 'past cases'.\n"
            "- Cite only principle ids (Pxxx) that literally appear in CONTEXT.\n"
            "- Do not use speculative language ('likely', 'probably', 'they must "
            "be…') about the customer's situation.\n\n"
            f"CONTEXT (from records):\n{context_text}\n\n"
            f"REP'S NOTE:\n{note}"
        )
    return (
        "あなたは経験豊富な営業マネージャーです。後輩がこのアカウントを訪問前に"
        "準備できるよう支援します。最優先は『根拠に基づくこと』。記録が裏づける"
        "ことだけを述べ、欠けている点はすべて『問い』に変え、断定しないこと。\n\n"
        "次の3つの見出しで、自然な日本語で書いてください:\n\n"
        "### 確認できている事実\n"
        "CONTEXT（記録: CRM・活動履歴・メモ・見積・受注・アカウント情報・"
        "決定論的シグナル）に明記された事実だけを記載する。数字（停滞日数・ランク"
        "経過日数・ランク・金額・日付）は記録どおり正確に引用する。推論・補完・"
        "要約で新しい事実を加えない。記録に顧客が見つからない場合は、メモに書かれた"
        "ことだけを記載する。\n"
        "各事実は、先頭に短い太字ラベルを付けた箇条書きで書く。例: "
        "`- **案件概要:** D065 …`。関連する事実は適切なラベル（顧客・案件概要・"
        "時系列・ステータス・活動・履歴 等）でまとめ、生のフィールド名を並べるのでは"
        "なく自然な文章にする。表現は任せるが、事実は記録どおりに保つ。\n\n"
        "### 確認すべき問い\n"
        "情報が欠けている点は、すべて『問い』の形で挙げる（断定しない）。次の"
        "未確認事項を問いとして含める: " + open_qs + "\n\n"
        "### 準備の提案\n"
        "上記の事実と問いだけから導ける、訪問前の具体的な準備を1〜3個。原則id"
        "（例: P001）は、下記 RELEVANT CORPUS KNOWLEDGE に出てくる場合のみ引用してよい。\n\n"
        "厳守ルール:\n"
        "- 顧客の隠れた動機・社内政治・関係者の振る舞い・予算に関する社内事情を推測しない。\n"
        "- 記録が裏づけない事項は断定せず『確認すべき問い』に回す（物語を作らない）。\n"
        f"- {cn} 以外の顧客名を出さない。{did} 以外の案件IDを出さない。\n"
        "- 他の顧客や過去事例を例として引用しない。例を創作しない。\n"
        "- CONTEXT に実際に出てくる原則id（Pxxx）以外は引用しない。\n"
        "- 顧客の状況について「おそらく」「可能性が高い」等の憶測表現を使わない。\n\n"
        f"CONTEXT（記録より）:\n{context_text}\n\n"
        f"後輩のメモ:\n{note}"
    )


def narrate_review(r: CoachReview, use_llm: bool = True) -> str:
    """Optionally let the model rephrase the SAME findings into smoother coaching
    language. The model is forbidden to add facts or pick one answer; on any
    failure we return the deterministic render."""
    fallback = format_review(r)
    if not use_llm:
        return fallback
    from senpai.llm import client

    try:
        out = client.simple_complete([{"role": "user", "content": narration_prompt(r)}])
        return out or fallback
    except Exception:  # noqa: BLE001 — server down → deterministic render
        return fallback
