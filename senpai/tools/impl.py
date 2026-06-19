"""Tool implementations + dispatch — mirrors demo/tools.py's contract.

Every executor returns a SHORT string (what the model sees as the tool result)
and `dispatch` never raises, so the chat loop can't crash. All data comes from
the deterministic store / scoring engine, so these run GPU-free.

`python -m senpai.tools.impl` runs a canned call per tool (smoke test).
"""
from __future__ import annotations

import json

from senpai import config
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.retrieval.playbook import find_similar_deals, retrieve_playbook
from senpai.tools.web import web_search


def _score_open_deals(rep_id: str = ""):
    """Score every open deal once (optionally limited to one rep). Returns a list
    of (deal, HealthResult, flags) — the shared backbone for the manager
    analytics tools and summarize_reports, so the scoring loop lives in one place."""
    deals = store.deals_for_rep(rep_id) if rep_id else store.open_deals()
    out = []
    for d in deals:
        if not config.is_open_rank(d.get("order_rank")):
            continue
        acts = store.activities_for_deal(d["deal_id"])
        res = score_deal(d, acts)
        flags = deal_flags(d, acts, health_band=res.band)
        out.append((d, res, flags))
    return out


def _resolve_customer(customer: str) -> dict | None:
    if not customer:
        return None
    return store.get_customer(customer) or store.find_customer_by_name(customer)


def _deal_line(d: dict) -> str:
    cust = store.customer_name(d["customer_id"])
    return (f"{d['deal_id']} {cust} / 担当{store.rep_name(store.deal_rep_id(d))} / "
            f"{d['order_rank']} / ¥{d['total_order_amount']:,} / "
            f"完了予定{d['expected_order_date']}")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def query_spr(customer: str = "", rep_id: str = "", deal_id: str = "") -> str:
    if deal_id:
        d = store.get_deal(deal_id)
        if not d:
            return f"案件 {deal_id} は見つかりません。"
        acts = store.activities_for_deal(deal_id)
        head = _deal_line(d)
        act_lines = [f"  ・{a['activity_date']} [{a['activity_type']}] {a['daily_report']}"
                     for a in acts[:3]]
        return head + ("\n直近の活動:\n" + "\n".join(act_lines) if act_lines else "")

    if customer:
        c = _resolve_customer(customer)
        if not c:
            return f"顧客「{customer}」は見つかりません。"
        deals = store.deals_for_customer(c["customer_id"])
        if not deals:
            return f"{c['name']} の案件はありません。"
        lines = [_deal_line(d) for d in deals]
        return f"{c['name']} の案件 {len(deals)}件:\n- " + "\n- ".join(lines)

    if rep_id:
        deals = store.deals_for_rep(rep_id)
        if not deals:
            return f"担当 {rep_id} の案件はありません。"
        lines = [_deal_line(d) for d in deals]
        return f"{store.rep_name(rep_id)} の案件 {len(deals)}件:\n- " + "\n- ".join(lines)

    return "customer / rep_id / deal_id のいずれかを指定してください。"


def find_similar_deals_tool(customer: str = "", industry: str = "") -> str:
    cid = ""
    if customer:
        c = _resolve_customer(customer)
        if c:
            cid = c["customer_id"]
    hits = find_similar_deals(customer_id=cid, industry=industry)
    if not hits:
        return "類似案件は見つかりませんでした。"
    lines = [_deal_line(d) for d in hits]
    return "類似案件:\n- " + "\n- ".join(lines)


def retrieve_playbook_tool(query: str = "", tags=None) -> str:
    if isinstance(tags, str):
        tags = [tags]
    hits = retrieve_playbook(query=query, tags=tags or [])
    if not hits:
        return "該当するプレイブックがありません。route_to_expert の利用を検討してください。"
    lines = []
    for e in hits:
        author = store.rep_name(e["author_rep_id"])
        lines.append(f"[{'/'.join(e['situation_tags'])}] {e['text']}(提供: {author})")
    return "プレイブック:\n- " + "\n- ".join(lines)


def lookup_customer_environment(customer: str = "") -> str:
    c = _resolve_customer(customer)
    if not c:
        return f"顧客「{customer}」は見つかりません。"
    env = store.get_environment(c["customer_id"])
    if not env:
        return f"{c['name']} の環境情報は未登録です。"
    return (f"{c['name']} の環境: PC={env['pc']} / OS={env['os']} / "
            f"ネットワーク={env['network']} / 備考: {env['notes']}")


def get_product_info(product: str = "") -> str:
    p = store.get_product(product.upper()) if product else None
    if not p:
        p = next((x for x in store.all_products()
                  if product and product in x["product_name"]), None)
    if not p:
        names = ", ".join(x["product_name"] for x in store.all_products())
        return f"製品「{product}」は見つかりません。取扱: {names}"
    return (f"{p['product_name']} ({p['product_code']} / {p['manufacturer_model_number']}) "
            f"— ¥{p['standard_unit_price']:,}\n"
            f"分類: {p['major']} > {p['mid']} > {p['minor']}\n"
            f"仕様: {p['specs']}\nマニュアル抜粋: {p['manual_ja']}")


def score_deal_health(deal_id: str = "") -> str:
    d = store.get_deal(deal_id)
    if not d:
        return f"案件 {deal_id} は見つかりません。"
    acts = store.activities_for_deal(deal_id)
    res = score_deal(d, acts)
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}[res.band]
    reasons = res.top_reasons(3)
    body = "／".join(reasons) if reasons else "目立ったリスク信号なし"
    return f"{emoji} {res.band}(リスク{res.score}/100): {body}"


def draft_daily_report(activity: str = "", deal_id: str = "") -> str:
    deal = store.get_deal(deal_id) if deal_id else None
    cust = store.customer_name(deal["customer_id"]) if deal else "(顧客未指定)"
    rank = deal["order_rank"] if deal else "-"
    next_action = "次回アクションを記入してください"
    if deal:
        res = score_deal(deal, store.activities_for_deal(deal_id))
        if res.band == "red":
            next_action = "健全度が赤。上長同席での再提案を打診"
    return ("【日報ドラフト】\n"
            f"顧客: {cust}\n"
            f"案件: {deal_id or '-'} / 受注ランク: {rank}\n"
            f"活動内容: {activity}\n"
            f"次アクション: {next_action}")


def review_sales_note(note: str = "", deal_id: str = "") -> str:
    """Bridge to the Sales Review Coach (a separate, friend-owned experiment under
    senpai.coach). Kept here only so the coach's own tests can reach it; it is NOT
    part of our chat tool surface. The coach is imported lazily so our pipeline's
    import graph never depends on it."""
    if not (note or "").strip():
        return "レビューするメモ・日報の本文を入力してください。"
    from senpai.coach.review import format_review, review_note   # lazy: keep us decoupled
    deal = store.get_deal(deal_id) if deal_id else None
    notes = store.notes_for_deal(deal_id) if deal else None
    report = store.report_for_deal(deal_id) if deal else None
    review = review_note(note, deal=deal, notes=notes, report=report)
    return format_review(review)


def route_to_expert(question: str = "", tags=None) -> str:
    if isinstance(tags, str):
        tags = [tags]
    tags = tags or []
    experts = [r for r in store.all_reps() if r["role"] in ("senior", "expert")]
    best, best_score = None, -1
    for r in experts:
        score = sum(1 for t in tags
                    if any(t in s or s in t for s in r["specialty_tags"]))
        score += sum(1 for s in r["specialty_tags"] if question and s in question)
        if r["is_top_performer"]:
            score += 0.5
        if score > best_score:
            best, best_score = r, score
    if not best:
        return "適切な担当が見つかりませんでした。"
    return (f"エキスパート紹介: {best['name']}({'/'.join(best['specialty_tags'])})\n"
            f"紹介メッセージ案: 「{best['name']}さん、{question} の件でご相談です。"
            "お手すきの際にご助言いただけますか。」")


def summarize_reports(rep_id: str = "") -> str:
    if not store.daily_reports_for_rep(rep_id):
        return f"担当 {rep_id} のレポートはありません。"
    scored = _score_open_deals(rep_id)
    lines = [f"{store.rep_name(rep_id)} のオープン案件 {len(scored)}件の要約:"]
    flagged = 0
    for d, _res, flags in scored:
        if flags:
            flagged += 1
            msgs = "／".join(f.message for f in flags[:2])
            lines.append(f"⚠ {d['deal_id']} {store.customer_name(d['customer_id'])}: {msgs}")
    lines.append(f"信頼性フラグの立った案件: {flagged}件")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Manager-facing analytics tools (all grounded in the deterministic engine)
# ---------------------------------------------------------------------------
_BAND_EMOJI = {"red": "🔴", "yellow": "🟡", "green": "🟢"}


def list_at_risk_deals(rep_id: str = "", band: str = "", limit: int = 10) -> str:
    """At-risk open deals across the team (or one rep), worst first. Defaults to
    red; pass band='yellow' (includes red+yellow) to widen."""
    scored = _score_open_deals(rep_id)
    if band == "yellow":
        keep = {"red", "yellow"}
    elif band in ("red", "green"):
        keep = {band}
    else:
        keep = {"red"}
    rows = sorted((t for t in scored if t[1].band in keep),
                  key=lambda t: t[1].score, reverse=True)
    if not rows:
        return "該当する要注意案件はありません。"
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    lines = []
    for d, res, _flags in rows[:limit]:
        reason = (res.top_reasons(1) or ["—"])[0]
        lines.append(f"{_BAND_EMOJI[res.band]} {d['deal_id']} "
                     f"{store.customer_name(d['customer_id'])} / 担当{store.rep_name(store.deal_rep_id(d))} / "
                     f"リスク{res.score} / {reason}")
    head = f"要注意案件 {len(rows)}件中 上位{min(limit, len(rows))}件:"
    return head + "\n- " + "\n- ".join(lines)


def team_pipeline_overview(rep_id: str = "") -> str:
    """Team pipeline at a glance: counts, ¥, stage spread, health split, flags."""
    scored = _score_open_deals(rep_id)
    if not scored:
        return "オープン案件がありません。"
    total = len(scored)
    pipeline = sum(d.get("total_order_amount", 0) for d, _, _ in scored)
    by_band = {"red": 0, "yellow": 0, "green": 0}
    by_rank: dict[str, int] = {}
    flagged = 0
    for d, res, flags in scored:
        by_band[res.band] += 1
        by_rank[d["order_rank"]] = by_rank.get(d["order_rank"], 0) + 1
        if flags:
            flagged += 1
    rank_str = "、".join(f"{r}:{n}" for r, n in sorted(by_rank.items()))
    scope = f"{store.rep_name(rep_id)} の" if rep_id else "チーム全体の"
    return (f"{scope}パイプライン概況:\n"
            f"- オープン案件: {total}件 / 想定金額: ¥{pipeline:,}\n"
            f"- 健全度: 🔴{by_band['red']} / 🟡{by_band['yellow']} / 🟢{by_band['green']}\n"
            f"- ランク別: {rank_str}\n"
            f"- 信頼性フラグの立った案件: {flagged}件")


def team_report_digest() -> str:
    """All reps' open deals digested into one manager view: flagged deals grouped
    by rep, worst first."""
    scored = _score_open_deals()
    by_rep: dict[str, list] = {}
    for d, res, flags in scored:
        if flags:
            by_rep.setdefault(store.deal_rep_id(d), []).append((d, res, flags))
    if not by_rep:
        return "信頼性フラグの立った案件はありません。チーム全体が健全です。"
    order = sorted(by_rep.items(), key=lambda kv: len(kv[1]), reverse=True)
    lines = [f"全担当の日報ダイジェスト（要注意 {sum(len(v) for v in by_rep.values())}件）:"]
    for rep_id, items in order:
        lines.append(f"\n【{store.rep_name(rep_id)}】フラグ{len(items)}件")
        for d, _res, flags in sorted(items, key=lambda t: t[1].score, reverse=True)[:5]:
            msg = (flags[0].message if flags else "—")
            lines.append(f"  ⚠ {d['deal_id']} {store.customer_name(d['customer_id'])}: {msg}")
    return "\n".join(lines)


def rep_coaching_focus() -> str:
    """Per-rep rollup so a manager sees where to spend coaching time."""
    scored = _score_open_deals()
    agg: dict[str, dict] = {}
    for d, res, flags in scored:
        a = agg.setdefault(store.deal_rep_id(d), {"deals": 0, "risk": 0, "red": 0, "flagged": 0})
        a["deals"] += 1
        a["risk"] += res.score
        if res.band == "red":
            a["red"] += 1
        if flags:
            a["flagged"] += 1
    if not agg:
        return "オープン案件がありません。"
    rows = sorted(agg.items(), key=lambda kv: (kv[1]["red"], kv[1]["flagged"]), reverse=True)
    lines = ["コーチング優先度（要注意の多い担当順）:"]
    for rep_id, a in rows:
        avg = round(a["risk"] / a["deals"]) if a["deals"] else 0
        lines.append(f"- {store.rep_name(rep_id)}: 案件{a['deals']} / "
                     f"🔴{a['red']} / フラグ{a['flagged']} / 平均リスク{avg}")
    return "\n".join(lines)


def draft_message(to: str = "", about: str = "", deal_id: str = "",
                  purpose: str = "") -> str:
    """Draft a short, editable Japanese message (rep nudge or client follow-up).
    Pulls deal context when deal_id is given. Never sends — human stays in the loop."""
    ctx = ""
    if deal_id:
        d = store.get_deal(deal_id)
        if d:
            res = score_deal(d, store.activities_for_deal(deal_id))
            ctx = (f"（{deal_id} {store.customer_name(d['customer_id'])} / {d['order_rank']} / "
                   f"健全度{_BAND_EMOJI[res.band]}{res.band}）")
    topic = about or purpose or "案件の状況確認"
    recipient = to or "担当者"
    body = (f"{recipient} 様\n\n"
            f"お疲れさまです。{topic} の件、現状を共有いただけますか。{ctx}\n"
            "次回の意思決定事項と完了予定日のすり合わせができればと思います。\n"
            "よろしくお願いいたします。")
    return f"【メッセージ下書き（送信はされません・編集してください）】\n{body}"


_FY_CONTEXT = {
    "q4": "1〜3月は年度末。予算消化の最後の好機。クロージングを強く。",
    "q1": "4〜6月は新年度。新規予算が付く時期。早期の種まきを。",
    "q2": "7〜9月は中間期。下期予算の検討が始まる。提案の仕込みを。",
    "q3": "10〜12月は下期序盤。年度末に向け案件を積み上げる時期。",
}


def get_seasonal_context(month: int = 0) -> str:
    m = int(month) if month else config.today().month
    if m in (1, 2, 3):
        key, label = "q4", "第4四半期(年度末)"
    elif m in (4, 5, 6):
        key, label = "q1", "第1四半期"
    elif m in (7, 8, 9):
        key, label = "q2", "第2四半期"
    else:
        key, label = "q3", "第3四半期"
    return f"{m}月 — {label}: {_FY_CONTEXT[key]}"


# ---------------------------------------------------------------------------
# Dispatch (mirrors demo/tools.py)
# ---------------------------------------------------------------------------
_DISPATCH = {
    "query_spr": query_spr,
    "find_similar_deals": find_similar_deals_tool,
    "retrieve_playbook": retrieve_playbook_tool,
    "lookup_customer_environment": lookup_customer_environment,
    "get_product_info": get_product_info,
    "score_deal_health": score_deal_health,
    "review_sales_note": review_sales_note,
    "draft_daily_report": draft_daily_report,
    "route_to_expert": route_to_expert,
    "summarize_reports": summarize_reports,
    "get_seasonal_context": get_seasonal_context,
    # Manager + shared tools
    "list_at_risk_deals": list_at_risk_deals,
    "team_pipeline_overview": team_pipeline_overview,
    "team_report_digest": team_report_digest,
    "rep_coaching_focus": rep_coaching_focus,
    "draft_message": draft_message,
    "web_search": web_search,
}


def dispatch(name: str, arguments: dict | str) -> str:
    """Execute a tool by name with arguments (dict or JSON string). Always
    returns a string; never raises (so the chat loop can't crash)."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return f"[error] could not parse arguments for {name}: {arguments!r}"
    if not isinstance(arguments, dict):
        arguments = {}
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"[error] unknown tool: {name}"
    try:
        return str(fn(**arguments))
    except TypeError as e:
        return f"[error] bad arguments for {name}: {e}"
    except Exception as e:  # noqa: BLE001 — must never crash on a tool
        return f"[error] {name} failed: {e}"


if __name__ == "__main__":
    # Pick a deliberately dead deal so score/flags show real risk.
    for n, a in [
        ("query_spr", {"deal_id": "D001"}),
        ("query_spr", {"rep_id": "R05"}),
        ("find_similar_deals", {"customer": "C01"}),
        ("retrieve_playbook", {"query": "お客様が決定を先延ばし", "tags": ["決定先延ばし"]}),
        ("lookup_customer_environment", {"customer": "C01"}),
        ("get_product_info", {"product": "MFP30"}),
        ("score_deal_health", {"deal_id": "D001"}),
        ("review_sales_note", {"note": "お客様は社内で検討してから連絡するとのこと。"}),
        ("draft_daily_report", {"activity": "アクメ商事を訪問しデモを実施", "deal_id": "D001"}),
        ("route_to_expert", {"question": "ネットワーク更改の構成相談", "tags": ["ネットワーク"]}),
        ("summarize_reports", {"rep_id": "R05"}),
        ("get_seasonal_context", {"month": 2}),
        ("list_at_risk_deals", {"limit": 5}),
        ("team_pipeline_overview", {}),
        ("team_report_digest", {}),
        ("rep_coaching_focus", {}),
        ("draft_message", {"to": "伊藤さん", "about": "D003の進捗", "deal_id": "D003"}),
        ("web_search", {"query": "製造業 IT投資 動向"}),
    ]:
        print(f"\n### {n}({a})\n{dispatch(n, a)}")
