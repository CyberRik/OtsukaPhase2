"""The persistent MatsudaContext object + how follow-ups are answered from it.

`MatsudaContext` is a fully-materialized snapshot: once `synthesize.py` builds it,
every field it needs to answer a follow-up already lives on the object. The
`answer()` method therefore never touches the data store — it routes a natural-
language question to one of the pre-synthesized views and formats a reply. This is
the whole point of the workflow: synthesize once, answer many times, no re-fetch.

`to_markdown()` renders the same snapshot as an inspectable report so a human can
see exactly what was retrieved and how it was synthesized.

Strings are Japanese-leaning (manager-facing), matching the rest of Senpai; the
question router accepts English or Japanese keywords so the demo reads naturally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

_BAND_EMOJI = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
_BAND_JA = {"red": "赤(高リスク)", "yellow": "黄(注意)", "green": "緑(良好)"}


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return "¥0"


@dataclass
class DealView:
    """One Matsuda deal, pre-joined with its owner, health and reliability flags."""
    deal_id: str
    name: str
    rank: str
    amount: int
    owner_id: str
    owner_name: str
    owner_role: str
    owner_specialties: list[str]
    product_codes: list[str]
    product_names: list[str]
    band: str
    score: int
    reasons: list[str]
    flags: list[str]
    has_decision_maker: bool
    last_contact: str | None
    expected_order_date: str | None
    activity_count: int

    @property
    def emoji(self) -> str:
        return _BAND_EMOJI.get(self.band, "⚪")

    def one_line(self) -> str:
        prod = "・".join(self.product_names) or "—"
        return (f"{self.emoji} {self.deal_id} {self.name} / {self.rank} / "
                f"{_yen(self.amount)} / 製品: {prod} / 担当: {self.owner_name} / "
                f"リスク{self.score}")


@dataclass
class MatsudaContext:
    """A persistent, single-object synthesis of everything known about Matsuda.

    Built once by `synthesize.build_matsuda_context()`. Follow-up questions are
    answered from these fields alone (see `answer`)."""
    built_at: date
    customer: dict
    environment: dict | None
    reps: list[dict]                       # distinct deal owners on the account
    deals: list[DealView]
    activity_timeline: list[dict]          # account-wide, newest first (normalized)
    products: list[dict]                   # resolved product info + which deals use it
    similar_deals: list[dict]              # feature-matched comparable deals
    won_similar_deals: list[dict]          # comparable deals we actually won
    playbook: list[dict]                   # relevant mined advice
    next_actions: list[str]                # synthesized recommendation list
    decision_maker_titles: list[str]       # decision-maker titles seen on the account
    retrieval_log: list[tuple] = field(default_factory=list)   # (source, what, n)

    # --- derived aggregates (computed in __post_init__) --------------------
    pipeline_total: int = 0
    band_counts: dict[str, int] = field(default_factory=dict)
    at_risk: list[DealView] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.pipeline_total = sum(d.amount for d in self.deals)
        self.band_counts = {"red": 0, "yellow": 0, "green": 0}
        for d in self.deals:
            self.band_counts[d.band] = self.band_counts.get(d.band, 0) + 1
        # Worst deals first; anything not green is "at risk".
        self.at_risk = sorted([d for d in self.deals if d.band != "green"],
                              key=lambda d: d.score, reverse=True)

    # ----------------------------------------------------------------------
    # Convenience accessors
    # ----------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self.customer.get("name", "Matsuda")

    @property
    def worst_deal(self) -> DealView | None:
        return self.at_risk[0] if self.at_risk else None

    def latest_activity(self) -> dict | None:
        return self.activity_timeline[0] if self.activity_timeline else None

    # ----------------------------------------------------------------------
    # Per-intent answers (each reads ONLY synthesized fields — no store access)
    # ----------------------------------------------------------------------
    def summary(self) -> str:
        c = self.customer
        red = self.band_counts.get("red", 0)
        yellow = self.band_counts.get("yellow", 0)
        head = (f"【{self.name}】{c.get('industry','—')} / {c.get('size','—')} / "
                f"オープン案件{len(self.deals)}件・合計{_yen(self.pipeline_total)}")
        health = (f"健全度: 🔴{red} / 🟡{yellow} / 🟢{self.band_counts.get('green',0)}")
        owners = "、".join(sorted({d.owner_name for d in self.deals})) or "—"
        lead = ""
        if self.worst_deal:
            w = self.worst_deal
            lead = (f"\n最注意: {w.emoji} {w.deal_id}（{w.name}）— "
                    f"{(w.reasons[:1] or ['—'])[0]}")
        env = ""
        if self.environment:
            env = f"\nIT環境: PC {self.environment.get('pc','—')} / {self.environment.get('network','—')}"
        return (f"{head}\n{health} / 担当: {owners}{lead}{env}\n"
                f"フォロー候補: {self.next_actions[0] if self.next_actions else '—'}")

    def answer_risks(self) -> str:
        if not self.at_risk:
            lines = ["目立ったリスク信号はありません。全案件が健全です。"]
        else:
            lines = [f"最大のリスクは {len(self.at_risk)} 件の要注意案件です（悪い順）:"]
            for d in self.at_risk:
                reasons = "／".join(d.reasons[:3]) if d.reasons else "—"
                lines.append(f"- {d.emoji} {d.deal_id} {d.name}（リスク{d.score}/100）: {reasons}")
                if d.flags:
                    lines.append(f"    信頼性フラグ: {'／'.join(d.flags[:2])}")
        return "\n".join(lines)

    def answer_decision_maker(self) -> str:
        seen = "、".join(self.decision_maker_titles) if self.decision_maker_titles else "（記録なし）"
        missing = [d for d in self.deals if not d.has_decision_maker]
        lines = [f"アカウント全体で接触した決裁者クラスの役職: {seen}"]
        if missing:
            lines.append("ただし以下の案件は決裁者が未特定です（最優先で特定すべき）:")
            for d in missing:
                lines.append(f"- {d.emoji} {d.deal_id} {d.name}（{d.rank}）")
        else:
            lines.append("全オープン案件で決裁者クラスへの接触が記録されています。")
        # ground the "how" in mined advice if we retrieved a DM playbook entry
        dm_pb = next((p for p in self.playbook
                      if any("決裁" in t for t in p.get("situation_tags", []))), None)
        if dm_pb:
            lines.append(f"進め方（プレイブック）: {dm_pb['text']}")
        return "\n".join(lines)

    def answer_last_meeting(self) -> str:
        a = self.latest_activity()
        if not a:
            return "活動履歴がありません。"
        deal = next((d for d in self.deals if d.deal_id == a.get("deal_id")), None)
        deal_label = f"{a.get('deal_id')}（{deal.name}）" if deal else (a.get("deal_id") or "—")
        return ("直近の接触:\n"
                f"- 日付: {a.get('activity_date')}\n"
                f"- 種別: {a.get('activity_type')}\n"
                f"- 案件: {deal_label}\n"
                f"- 相手: {a.get('business_card_info') or '—'}\n"
                f"- 課題: {a.get('customer_challenge') or '—'}\n"
                f"- 内容: {a.get('daily_report') or '—'}")

    def answer_products(self) -> str:
        if not self.products:
            return "関心製品は特定できていません。"
        lines = ["検討中の製品（案件で引き合いのあるもの）:"]
        for p in self.products:
            deals = "、".join(p["deal_ids"])
            lines.append(f"- {p['product_name']}（{p['product_code']}）{_yen(p['standard_unit_price'])} "
                         f"／ 分類 {p['major']}>{p['mid']}>{p['minor']} ／ 該当案件: {deals}")
        return "\n".join(lines)

    def answer_next_action(self) -> str:
        if not self.next_actions:
            return "特筆すべき次アクションはありません。"
        lines = ["推奨アクション（優先度順）:"]
        for i, act in enumerate(self.next_actions, 1):
            lines.append(f"{i}. {act}")
        return "\n".join(lines)

    def answer_similar_won(self) -> str:
        if not self.won_similar_deals:
            return "類似条件で受注済みの案件は見つかりませんでした。"
        lines = [f"受注済みの類似案件 {len(self.won_similar_deals)}件（参考に使える勝ち筋）:"]
        for d in self.won_similar_deals:
            lines.append(f"- {d['deal_id']} {d['customer_name']}（{d['industry']}/{d['size']}）"
                         f"{d['order_rank']} / {_yen(d['total_order_amount'])}")
        return "\n".join(lines)

    def answer_similar(self) -> str:
        if not self.similar_deals:
            return "類似案件は見つかりませんでした。"
        lines = [f"類似案件 {len(self.similar_deals)}件:"]
        for d in self.similar_deals:
            lines.append(f"- {d['deal_id']} {d['customer_name']}（{d['industry']}/{d['size']}）"
                         f"{d['order_rank']} / {_yen(d['total_order_amount'])}")
        return "\n".join(lines)

    def answer_health(self) -> str:
        lines = [f"健全度サマリ（{self.name} / オープン{len(self.deals)}件）:",
                 f"- 🔴{self.band_counts.get('red',0)} / "
                 f"🟡{self.band_counts.get('yellow',0)} / "
                 f"🟢{self.band_counts.get('green',0)} / 合計{_yen(self.pipeline_total)}"]
        for d in self.deals:
            reasons = "／".join(d.reasons[:2]) if d.reasons else "リスク信号なし"
            lines.append(f"- {d.emoji} {d.deal_id} {_BAND_JA[d.band]}（リスク{d.score}）: {reasons}")
        return "\n".join(lines)

    def answer_environment(self) -> str:
        e = self.environment
        if not e:
            return f"{self.name} のIT環境情報は未登録です。"
        return (f"{self.name} のIT環境:\n"
                f"- PC: {e.get('pc','—')}\n"
                f"- OS: {e.get('os','—')}\n"
                f"- ネットワーク: {e.get('network','—')}\n"
                f"- 備考: {e.get('notes','—')}")

    def answer_owner(self) -> str:
        lines = ["担当者（案件オーナー）:"]
        for r in self.reps:
            spec = "・".join(r.get("specialty_tags", [])) or "—"
            owned = [d.deal_id for d in self.deals if d.owner_id == r["employee_id"]]
            lines.append(f"- {r['name']}（{r.get('role','—')} / 専門: {spec}）担当案件: {'、'.join(owned)}")
        return "\n".join(lines)

    def answer_pipeline(self) -> str:
        lines = [f"{self.name} のパイプライン: オープン{len(self.deals)}件 / 合計{_yen(self.pipeline_total)}"]
        for d in sorted(self.deals, key=lambda d: d.amount, reverse=True):
            lines.append(f"- {d.deal_id} {d.name}: {_yen(d.amount)}（{d.rank} / {d.emoji}）")
        return "\n".join(lines)

    # ----------------------------------------------------------------------
    # Question router — keyword based, English or Japanese, most-specific-first.
    # ----------------------------------------------------------------------
    def answer(self, question: str) -> str:
        q = (question or "").lower()

        def has(*words: str) -> bool:
            return any(w in q for w in words)

        # Order matters: check the most specific intents first.
        if has("decision maker", "decision-maker", "who decides", "決裁", "決裁者"):
            return self.answer_decision_maker()
        if has("similar", "類似", "comparable", "reference deal", "won", "win", "勝"):
            # "similar … won" vs plain "similar"
            if has("won", "win", "勝", "受注", "success"):
                return self.answer_similar_won()
            return self.answer_similar()
        if has("risk", "リスク", "concern", "worry", "danger", "problem", "issue", "懸念"):
            return self.answer_risks()
        if has("last meeting", "last contact", "happened", "recent meeting",
               "前回", "直近", "最近", "last time", "meeting"):
            return self.answer_last_meeting()
        if has("product", "製品", "interested in", "buying", "purchase", "引き合い"):
            return self.answer_products()
        if has("next", "should i do", "do next", "recommend", "次に", "アクション",
               "action", "advice", "どうすれ"):
            return self.answer_next_action()
        if has("environment", "環境", "infrastructure", "network", "ネットワーク",
               "it setup", "システム環境"):
            return self.answer_environment()
        if has("health", "健全", "status", "score", "状況"):
            return self.answer_health()
        if has("who owns", "owner", "rep", "担当", "responsible", "in charge"):
            return self.answer_owner()
        if has("pipeline", "total value", "worth", "amount", "金額", "biggest deal",
               "largest", "value"):
            return self.answer_pipeline()
        # Default: an overall summary (also catches "tell me about Matsuda").
        return self.summary()

    # ----------------------------------------------------------------------
    # Inspectable markdown report
    # ----------------------------------------------------------------------
    def to_markdown(self) -> str:
        c = self.customer
        L: list[str] = []
        L.append(f"# MatsudaContext — {self.name}")
        L.append("")
        L.append(f"> Synthesized {self.built_at.isoformat()} · "
                 f"deterministic (GPU-free) · answered without re-fetching data")
        L.append("")

        # Retrieval provenance
        L.append("## 1. What was retrieved")
        L.append("")
        L.append("| Source | What | Count |")
        L.append("|---|---|---|")
        for src, what, n in self.retrieval_log:
            L.append(f"| `{src}` | {what} | {n} |")
        L.append("")

        # Customer record
        L.append("## 2. Customer record")
        L.append("")
        L.append(f"- **ID / Name:** {c.get('customer_id')} — {c.get('name')}")
        L.append(f"- **Industry / Size:** {c.get('industry','—')} / {c.get('size','—')}")
        L.append(f"- **Profile tags:** {', '.join(c.get('profile_tags', [])) or '—'}")
        L.append(f"- **Web presence:** {'yes' if c.get('has_web_presence') else 'no'}")
        L.append("")

        # Owners
        L.append("## 3. Account team (deal owners)")
        L.append("")
        for r in self.reps:
            owned = [d.deal_id for d in self.deals if d.owner_id == r["employee_id"]]
            L.append(f"- **{r['name']}** ({r['employee_id']}, {r.get('role','—')}) — "
                     f"specialty: {', '.join(r.get('specialty_tags', [])) or '—'} — "
                     f"deals: {', '.join(owned)}")
        L.append("")

        # Environment
        L.append("## 4. IT environment")
        L.append("")
        if self.environment:
            e = self.environment
            L.append(f"- PC: {e.get('pc','—')}")
            L.append(f"- OS: {e.get('os','—')}")
            L.append(f"- Network: {e.get('network','—')}")
            L.append(f"- Notes: {e.get('notes','—')}")
        else:
            L.append("_Not registered._")
        L.append("")

        # Deals + health
        L.append("## 5. Active deals + health signals")
        L.append("")
        L.append(f"Pipeline: **{len(self.deals)} open deals · {_yen(self.pipeline_total)}** — "
                 f"🔴{self.band_counts.get('red',0)} / 🟡{self.band_counts.get('yellow',0)} / "
                 f"🟢{self.band_counts.get('green',0)}")
        L.append("")
        L.append("| Deal | Name | Rank | Amount | Products | Owner | Health | Risk | DM? |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for d in self.deals:
            L.append(f"| {d.deal_id} | {d.name} | {d.rank} | {_yen(d.amount)} | "
                     f"{'・'.join(d.product_names) or '—'} | {d.owner_name} | "
                     f"{d.emoji} {d.band} | {d.score} | {'✓' if d.has_decision_maker else '✗'} |")
        L.append("")
        for d in self.deals:
            if d.reasons or d.flags:
                L.append(f"**{d.deal_id} {d.name}** — health {d.emoji} {d.band} (risk {d.score})")
                for r in d.reasons:
                    L.append(f"  - risk signal: {r}")
                for fl in d.flags:
                    L.append(f"  - reliability flag: {fl}")
                L.append("")

        # Activity timeline
        L.append("## 6. Recent activity timeline (account-wide, newest first)")
        L.append("")
        for a in self.activity_timeline:
            L.append(f"- **{a.get('activity_date')}** [{a.get('activity_type')}] "
                     f"deal {a.get('deal_id') or '—'} · {a.get('business_card_info') or '—'} — "
                     f"{a.get('daily_report') or '—'}")
        L.append("")

        # Products
        L.append("## 7. Products of interest")
        L.append("")
        for p in self.products:
            L.append(f"- **{p['product_name']}** ({p['product_code']}) — {_yen(p['standard_unit_price'])} — "
                     f"{p['major']} > {p['mid']} > {p['minor']} — deals: {', '.join(p['deal_ids'])}")
        L.append("")

        # Decision maker
        L.append("## 8. Decision-maker analysis")
        L.append("")
        L.append(f"- Titles contacted on the account: "
                 f"{', '.join(self.decision_maker_titles) or '（none recorded）'}")
        missing = [d.deal_id for d in self.deals if not d.has_decision_maker]
        L.append(f"- Deals still missing a decision-maker: {', '.join(missing) or 'none'}")
        L.append("")

        # Similar / won
        L.append("## 9. Similar deals")
        L.append("")
        L.append("**Comparable (feature-matched):**")
        for d in self.similar_deals:
            L.append(f"- {d['deal_id']} {d['customer_name']} ({d['industry']}/{d['size']}) "
                     f"{d['order_rank']} · {_yen(d['total_order_amount'])}")
        L.append("")
        L.append("**Won comparables (proof points):**")
        if self.won_similar_deals:
            for d in self.won_similar_deals:
                L.append(f"- {d['deal_id']} {d['customer_name']} ({d['industry']}/{d['size']}) "
                         f"{d['order_rank']} · {_yen(d['total_order_amount'])}")
        else:
            L.append("- _none found_")
        L.append("")

        # Playbook
        L.append("## 10. Relevant playbook (mined advice)")
        L.append("")
        for p in self.playbook:
            L.append(f"- [{'/'.join(p.get('situation_tags', []))}] {p['text']}")
        L.append("")

        # Next actions
        L.append("## 11. Synthesized next actions")
        L.append("")
        for i, act in enumerate(self.next_actions, 1):
            L.append(f"{i}. {act}")
        L.append("")
        return "\n".join(L)
