"""Ringi Boardroom Simulation — deterministic script for the consensus theater.

Japanese B2B deals are won or lost behind closed doors during the *Ringi* (稟議)
consensus process, where the customer's buying committee debates a proposal. This
module dramatizes that black box: it runs the SAME deterministic engines the
dashboard uses (`score_deal`, `deal_flags`, `compute_issues`) and maps each fired
coaching issue to a buyer persona (課長 Kacho / 部長 Bucho / 社長 Shacho), a
plain-Japanese objection, an Approval-meter deduction, and a "Senpai whisper" that
translates the objection back into the concrete sales data-point that caused it.

Nothing here is guessed. The approval numbers, which personas speak, and every
meter delta are 100% deterministic. The API layer streams fluid phrasing over the
`text` of each beat via the served model, falling back to that same `text` when the
model is unreachable — so the theater always runs (the demo's "never breaks" rule).

The re-run loop is what makes it a training dojo: pass a session-scoped
`overlay_activities` list (e.g. a fresh daily report + a decision-maker's business
card) and the objections that those actions resolve simply stop firing, the risk
score drops, and the meter climbs — all recomputed, never scripted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from senpai import config
from senpai.coaching import ISSUE_PRIORITY, compute_issues
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.retrieval.playbook import retrieve_playbook

# Persona keys (display metadata — icon/title/name — lives in the frontend).
KACHO = "kacho"    # 課長 — Section Manager / tech champion (specs, site survey)
BUCHO = "bucho"    # 部長 — Department Manager / economic buyer (budget, DM, margin)
SHACHO = "shacho"  # 社長 — CEO / ultimate approver (reliability, timing, verdict)
SENPAI = "senpai"  # 先輩 — the guardian-angel coach (not a boardroom seat)

# `close_date_passed` is a reliability *flag* (not a compute_issues issue), but the
# design gives it a distinct Shacho voice ("this close date has already passed").
# We treat it as a synthetic issue key so it slots into the same beat machinery.
CLOSE_DATE = "close_date_passed"

# Which persona voices each issue.
PERSONA_BY_ISSUE: dict[str, str] = {
    "confidence_mismatch": SHACHO,
    "missing_decision_maker": BUCHO,
    "long_inactivity": SHACHO,
    CLOSE_DATE: SHACHO,
    "premature_discount": BUCHO,
    "repeated_unresolved": KACHO,
    "weak_customer_discovery": KACHO,
    "incomplete_reports": KACHO,
}

# Relative severity weight — how the (deterministic) total risk is split across the
# voiced objections for the running meter. The TOTAL is authoritative (it equals
# the real risk score); the per-beat split is an illustrative presentation heuristic.
_SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}
_ISSUE_SEVERITY: dict[str, str] = dict(ISSUE_PRIORITY)
_ISSUE_SEVERITY[CLOSE_DATE] = "high"

# Corrective playbook tags per issue — fed to retrieve_playbook() for the RAG
# "Playbook Intervention Card" surfaced between runs.
_TAGS_BY_ISSUE: dict[str, list[str]] = {
    "confidence_mismatch": ["情報確認", "決定先延ばし"],
    "missing_decision_maker": ["決裁者未特定", "決裁者同席"],
    "long_inactivity": ["決定先延ばし", "クロージング"],
    CLOSE_DATE: ["クロージング", "決定先延ばし"],
    "premature_discount": ["値引き", "決裁者未特定"],
    "repeated_unresolved": ["段階的アプローチ", "情報確認"],
    "weak_customer_discovery": ["情報確認", "提案"],
    "incomplete_reports": ["情報確認"],
}

# Beat ordering — most-severe voices first (mirrors coaching.ISSUE_PRIORITY, with
# the close-date flag slotted next to inactivity).
_ORDER = [
    "confidence_mismatch",
    "missing_decision_maker",
    "long_inactivity",
    CLOSE_DATE,
    "premature_discount",
    "repeated_unresolved",
    "weak_customer_discovery",
    "incomplete_reports",
]


@dataclass
class Beat:
    """One line in the boardroom debate."""
    persona: str                 # kacho | bucho | shacho | senpai
    text: str                    # deterministic JP line — LLM brief AND fallback
    approval_delta: int = 0      # meter change (negative = objection, 0 = framing/advice)
    whisper: str = ""            # Senpai HUD translation → sales data-point
    issue: str | None = None     # source issue key (None for framing/advice beats)
    tags: list[str] = field(default_factory=list)


@dataclass
class RingiScript:
    deal_id: str
    deal_name: str
    customer: str
    base_approval: int           # 100 - risk, current-state ground truth
    final_approval: int          # where the meter lands after the debate (== base_approval)
    band: str                    # red | yellow | green
    beats: list[Beat] = field(default_factory=list)
    intervention: dict | None = None   # {entry_id, text, tags} from the playbook (RAG)
    issues: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Objection / whisper phrasing — deterministic, params from the real records.
# --------------------------------------------------------------------------- #
def _objection(issue: str, p: dict, deal_name: str) -> str:
    rank = p.get("rank", "-")
    if issue == "confidence_mismatch":
        return (f"『{rank}』ランクだと聞いていたが、現場を見ると健全度は赤だ。"
                "この見立ては本当に信用していいのかね?")
    if issue == "missing_decision_maker":
        return ("正直に言うが、大塚の担当者から私は一度も話を聞いていない。"
                f"日報は{p.get('reports', 0)}件あるそうだが、この案件は一体誰が回しているんだ?")
    if issue == "long_inactivity":
        return (f"最後の接触から{p.get('days', 0)}日も空いているじゃないか。"
                "なぜここまで放置されている?本気で進める気があるのか。")
    if issue == CLOSE_DATE:
        return ("完了予定日はとっくに過ぎている。なぜこんなに遅れているんだ?"
                "計画そのものが甘かったのではないか。")
    if issue == "premature_discount":
        return (f"決裁者も固まらないうちに、先方はもう{p.get('rate', 0)}%も値引きしてきた。"
                "本当の利益率はどうなっている?足元を見られていないか。")
    if issue == "repeated_unresolved":
        return (f"ランクが {p.get('init', '-')} から {p.get('rank', '-')} へ後退している。"
                "同じ課題がずっと片付いていない、ということだろう。")
    if issue == "weak_customer_discovery":
        return ("カタログは見せてくれるが、うちの現場調査は"
                f"{p.get('total', 0)}件中{p.get('filled', 0)}件しかできていない。"
                "実際の運用量を分かって提案しているのか?")
    if issue == "incomplete_reports":
        return ("提案の必須項目がまだ埋まっていない。この状態では、"
                "そもそも稟議に上げようがないよ。")
    return "この案件には、まだ気になる点がある。"


def _whisper(issue: str, p: dict) -> str:
    rank = p.get("rank", "-")
    if issue == "confidence_mismatch":
        return f"『信頼度と実態のズレ』検知 — 楽観ランク({rank})なのに健全度は赤です。自己申告を鵜呑みにできません。"
    if issue == "missing_decision_maker":
        return "『決裁者未特定』フラグ — キーマンに一度も接触できていません。日報を重ねても決裁は下りません。"
    if issue == "long_inactivity":
        return f"『停滞』フラグ — {p.get('days', 0)}日ノータッチで案件が冷えています。接触が空くほど決裁は遠のきます。"
    if issue == CLOSE_DATE:
        return "『完了予定日超過』フラグ — 想定クローズを過ぎています。予定日の甘さは社長に必ず突かれます。"
    if issue == "premature_discount":
        return f"『早期値引き』フラグ — 決裁者特定より先に{p.get('rate', 0)}%値引きしています。利益率への不信を招きます。"
    if issue == "repeated_unresolved":
        return f"『ランク後退』({p.get('init', '-')}→{p.get('rank', '-')}) — 同じ課題が繰り返し未解決です。"
    if issue == "weak_customer_discovery":
        return f"『顧客理解不足』 — {p.get('total', 0)}件中{p.get('filled', 0)}件しか課題把握できていません。現場調査が要ります。"
    if issue == "incomplete_reports":
        return "『必須項目未入力』 — 日報の抜け漏れです。稟議書に必要な情報が揃っていません。"
    return "リスク要因を検知しました。"


def _senpai_beat(top_issue: str | None, intervention: dict | None) -> Beat:
    """The guardian-angel coach's read of the room + the corrective principle."""
    if intervention and intervention.get("text"):
        text = f"見えましたか。ここが分かれ目です。定石はこうです — 「{intervention['text']}」"
    elif top_issue:
        text = "見えましたか。今の反対は、日報のデータがそのまま漏れている証拠です。"
    else:
        text = "反対が出ませんでしたね。データが揃っていると、稟議はこう静かに通ります。"
    return Beat(persona=SENPAI, text=text, approval_delta=0,
                whisper="顧客の反対は感情ではなくデータで動きます。フラグを一つ潰すごとに承認率は戻ります。",
                issue=None, tags=[])


# --------------------------------------------------------------------------- #
# Meter math — the running deltas always land exactly on base_approval.
# --------------------------------------------------------------------------- #
def _distribute(total: int, issues: list[str]) -> list[int]:
    """Split `total` risk points across the voiced objections by severity weight.
    Guarantees the deltas sum to exactly `total`, so the meter lands on base_approval."""
    if not issues:
        return []
    weights = [_SEVERITY_WEIGHT.get(_ISSUE_SEVERITY.get(i, "medium"), 2) for i in issues]
    wsum = sum(weights) or 1
    deltas: list[int] = []
    acc = 0
    for idx, w in enumerate(weights):
        if idx < len(weights) - 1:
            d = round(total * w / wsum)
        else:
            d = total - acc          # last beat absorbs the rounding remainder
        acc += d
        deltas.append(d)
    return deltas


def _intervention(issue_keys: list[str]) -> dict | None:
    """RAG: retrieve the single most relevant playbook entry for the fired issues."""
    tags: list[str] = []
    for k in issue_keys:
        for t in _TAGS_BY_ISSUE.get(k, []):
            if t not in tags:
                tags.append(t)
    if not tags:
        return None
    hits = retrieve_playbook(tags=tags, limit=1)
    if not hits:
        return None
    e = hits[0]
    return {"entry_id": e.get("entry_id"), "text": e.get("text", ""),
            "tags": e.get("situation_tags", [])}


# --------------------------------------------------------------------------- #
# Public entry point.
# --------------------------------------------------------------------------- #
def simulate_ringi(deal_id: str, overlay_activities: list[dict] | None = None,
                   today: date | None = None) -> RingiScript:
    """Build the deterministic boardroom script for one deal.

    `overlay_activities` are session-scoped rows (e.g. a sandbox draft turned into a
    seed-shaped activity) layered on top of the deal's real activities IN MEMORY —
    no store mutation, no disk write. Re-running with an overlay is how the training
    loop clears objections and lifts the meter.
    """
    today = today or config.today()
    deal = store.get_deal(deal_id)
    if not deal:
        raise ValueError(f"Unknown deal_id: {deal_id!r}")

    # Overlay first so a fresh row is treated as the newest activity by the engines.
    acts = list(overlay_activities or []) + store.activities_for_deal(deal_id)

    res = score_deal(deal, acts, today=today)
    flags = deal_flags(deal, acts, health_band=res.band, today=today)
    issues = compute_issues(deal, acts, res, flags, today)

    base_approval = 100 - res.score
    customer = store.customer_name(deal["customer_id"])
    deal_name = deal.get("deal_name", deal_id)

    # Index issue params by key; splice in the close-date flag as a synthetic issue.
    params_by_issue: dict[str, dict] = {it["issue"]: it.get("params", {}) for it in issues}
    if any(f.name == CLOSE_DATE for f in flags):
        params_by_issue[CLOSE_DATE] = {}

    fired = [k for k in _ORDER if k in params_by_issue]

    beats: list[Beat] = []
    # 1. Opening — Shacho convenes the committee.
    beats.append(Beat(persona=SHACHO,
                      text=f"では、{deal_name}の稟議を始めよう。各部門、忌憚のない意見を聞かせてくれ。",
                      approval_delta=0,
                      whisper="社長・部長・課長の三者が卓を囲みます。承認率の初期値は健全度エンジンが算出した実データです。",
                      issue=None))

    # 2. Objection beats — deltas sum to exactly res.score → meter lands on base_approval.
    deltas = _distribute(res.score, fired)
    for issue, delta in zip(fired, deltas):
        p = params_by_issue[issue]
        beats.append(Beat(
            persona=PERSONA_BY_ISSUE.get(issue, SHACHO),
            text=_objection(issue, p, deal_name),
            approval_delta=-delta,
            whisper=_whisper(issue, p),
            issue=issue,
            tags=_TAGS_BY_ISSUE.get(issue, []),
        ))

    intervention = _intervention(fired)

    if not fired:
        # Happy path — every risk cleared. Personas defend the project; Shacho approves.
        beats.append(Beat(persona=KACHO,
                          text="仕様も現場調査も問題ありません。技術的にはすぐ着手できます。",
                          approval_delta=0,
                          whisper="技術要件クリア。課長は推進に前向きです。", issue=None))
        beats.append(Beat(persona=BUCHO,
                          text="決裁者とも握れているし、値引きの根拠も明確だ。投資対効果は納得できる。",
                          approval_delta=0,
                          whisper="決裁者特定・利益率ともにフラグなし。部長は予算を承認する構えです。", issue=None))

    # 3. Senpai coaching beat (the guardian-angel read + corrective principle).
    beats.append(_senpai_beat(fired[0] if fired else None, intervention))

    # 4. Closing verdict from Shacho, matched to the deterministic band. The verdict
    #    beat absorbs any residual so the running meter (100 → sum of deltas) lands
    #    EXACTLY on base_approval in every case — including the happy path, where the
    #    unvoiced baseline risk (e.g. rank stagnation) shows as a small final settle.
    voiced = sum(deltas)           # positive total already deducted by the objections
    residual = res.score - voiced  # 0 in the fail case; == res.score when unvoiced
    if res.band == "red":
        verdict = "この状態では決裁できない。指摘された点を潰してから、もう一度上げてくれ。"
    elif res.band == "yellow":
        verdict = "方向性は悪くない。だが、まだ詰めが甘い。指摘点を解消して再提出してくれ。"
    else:
        verdict = "よくやった。これなら承認できる。契約へ進めよう。"
    beats.append(Beat(persona=SHACHO, text=verdict, approval_delta=-residual,
                      whisper=f"最終承認率 {base_approval}%(健全度: {res.band})。この数字はエンジンが算出した実測値です。",
                      issue=None))

    return RingiScript(
        deal_id=deal_id,
        deal_name=deal_name,
        customer=customer,
        base_approval=base_approval,
        final_approval=base_approval,
        band=res.band,
        beats=beats,
        intervention=intervention,
        issues=fired,
    )
