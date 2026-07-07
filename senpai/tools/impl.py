"""Tool implementations + dispatch — mirrors demo/tools.py's contract.

Every executor returns a SHORT string (what the model sees as the tool result)
and `dispatch` never raises, so the chat loop can't crash. All data comes from
the deterministic store / scoring engine, so these run GPU-free.

`python -m senpai.tools.impl` runs a canned call per tool (smoke test).
"""
from __future__ import annotations

import json
import re

from senpai import config
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.retrieval.knowledge import search_knowledge as _search_knowledge
from senpai.retrieval.playbook import find_similar_deals, retrieve_playbook
from senpai.tools.focus import session_focus
from senpai.tools.web import web_search
from senpai.tools.crawl import web_research


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
    """Alias-aware: resolves JA / English / romaji / known-alias forms (e.g.
    'Aozora Services' -> あおぞらサービス) before any retrieval."""
    if not customer:
        return None
    return store.resolve_customer(customer)


def _deal_line(d: dict) -> str:
    # The deal_name (e.g. "藤本食品 複合機案件") and product_category are what let the
    # model pick the deal the rep actually named — a request for "複合機案件" must not
    # silently resolve to the biggest open deal. The name already carries the customer.
    cust = store.customer_name(d["customer_id"])
    label = (d.get("deal_name") or "").strip() or cust
    cat = (d.get("product_category") or "").strip()
    if cat:
        label = f"{label}（{cat}）"
    return (f"{d['deal_id']} {label} / 担当{store.rep_name(store.deal_rep_id(d))} / "
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


def find_deals(product_category: str = "", industry: str = "", size: str = "",
               outcome: str = "", order_rank: str = "", min_amount=None,
               max_amount=None, product_code: str = "", limit: int = 10) -> str:
    """Grounded faceted search over real past/current deals. Filters the actual SPR
    fields (deal product_category / order_rank / amount / product code, customer
    industry / size) and reports the win/lost/open breakdown of the matches, so the
    model answers 'show me past <category> deals at <size>/<industry> companies and
    how they went' from data — never from invention."""
    from senpai.retrieval.deals import deal_facets, find_deals as _find, outcome_breakdown
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    all_hits = _find(product_category=product_category, industry=industry, size=size,
                     outcome=outcome, order_rank=order_rank, min_amount=min_amount,
                     max_amount=max_amount, product_code=product_code, limit=0)
    cond = "／".join(str(x) for x in [product_category, industry, size, outcome,
                                      order_rank, product_code] if x) or "全条件"
    if not all_hits:
        f = deal_facets()
        return ("条件に合う案件は見つかりませんでした。指定可能な値:\n"
                f"- 商品カテゴリ: {'、'.join(f['product_category'])}\n"
                f"- 業種: {'、'.join(f['industry'])}\n"
                f"- 規模: {'、'.join(f['size'])}\n"
                f"- 受注ランク: {'、'.join(f['order_rank'])}\n"
                "- 結果(outcome): won / lost / open")
    bd = outcome_breakdown(all_hits)
    head = (f"該当案件【{cond}】{len(all_hits)}件 "
            f"(受注{bd['won']}／失注{bd['lost']}／進行中{bd['open']}):")
    lines = []
    for d in all_hits[:limit]:
        cust = store.get_customer(d["customer_id"]) or {}
        lines.append(f"{d['deal_id']} {store.customer_name(d['customer_id'])}"
                     f"（{cust.get('industry', '-')}/{cust.get('size', '-')}）"
                     f" {d.get('product_category', '-')} / {d.get('order_rank', '-')}"
                     f" / ¥{d.get('total_order_amount', 0):,}")
    return head + "\n- " + "\n- ".join(lines)


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
        entry_id = e.get("entry_id", "Unknown")
        lines.append(f"[{'/'.join(e['situation_tags'])}] {e['text']}(出典: Playbook {entry_id})")
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


def morning_briefing(rep_id: str = "", limit: int = 10) -> str:
    """The rep's prioritized next-best-action worklist for today (or the whole
    team if no rep). Thin wrapper over senpai.briefing."""
    from senpai.briefing import format_briefing
    from senpai.briefing import morning_briefing as _briefing
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    items = _briefing(rep_id=rep_id, limit=limit)
    return format_briefing(items, rep_id=rep_id)


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
# Sales demo tools — ported from demo/tools.py, re-grounded on the real store
# ---------------------------------------------------------------------------
def _resolve_product(product: str) -> dict | None:
    """Resolve a product by code (e.g. 'MFP30') or a (fuzzy) name match."""
    if not product:
        return None
    p = store.get_product(str(product).strip().upper())
    if p:
        return p
    pl = str(product).strip().lower()
    for x in store.all_products():
        if pl == x["product_name"].lower():
            return x
    for x in store.all_products():
        if pl in x["product_name"].lower() or x["product_name"].lower() in pl:
            return x
    return None


def search_products(category: str = "", max_price: float = None,
                    min_price: float = None, keyword: str = "") -> str:
    """Search the real Otsuka product catalog by category / price band / keyword."""
    hits = []
    for p in store.all_products():
        cat = f"{p.get('major', '')} {p.get('mid', '')} {p.get('minor', '')}"
        if category and category.strip() not in cat:
            continue
        price = p.get("standard_unit_price", 0)
        if max_price is not None and price > float(max_price):
            continue
        if min_price is not None and price < float(min_price):
            continue
        if keyword:
            k = keyword.strip()
            if k not in p["product_name"] and k not in p.get("specs", ""):
                continue
        hits.append(p)
    if not hits:
        return "条件に合う製品は見つかりませんでした。"
    hits.sort(key=lambda p: p.get("standard_unit_price", 0))
    lines = [f"{p['product_code']} — {p['product_name']} — ¥{p['standard_unit_price']:,}"
             f"（{p.get('mid', p.get('major', ''))}）" for p in hits]
    return f"該当製品 {len(hits)}件:\n- " + "\n- ".join(lines)


def create_quote(items, discount_pct: float = 0, customer: str = "",
                 tax_pct: float = 10) -> str:
    """Build a price quote (estimate) from real catalog products: line totals,
    optional discount, tax, grand total. Never persisted — the rep edits/sends."""
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            return "[error] 見積項目を解析できませんでした。"
    if not isinstance(items, list) or not items:
        return "[error] 見積する製品がありません。"
    lines, skipped, subtotal = [], [], 0
    for it in items:
        if not isinstance(it, dict):
            continue
        p = _resolve_product(it.get("sku") or it.get("name") or it.get("product") or "")
        qty = int(it.get("qty", 1) or 1)
        if not p:
            skipped.append(str(it.get("sku") or it.get("name") or it.get("product")))
            continue
        price = p.get("standard_unit_price", 0)
        line_total = price * qty
        subtotal += line_total
        lines.append(f"  {qty} × {p['product_name']} @ ¥{price:,} = ¥{line_total:,}")
    if not lines:
        return f"[error] 指定された製品が見つかりませんでした: {', '.join(skipped)}"
    discount_pct = float(discount_pct or 0)
    tax_pct = float(tax_pct if tax_pct is not None else 10)
    discount = round(subtotal * discount_pct / 100)
    taxed_base = subtotal - discount
    tax = round(taxed_base * tax_pct / 100)
    total = taxed_base + tax
    header = f"見積書（{customer}様）" if customer else "見積書"
    out = [f"【{header}・ドラフト／送信はされません】", "明細:", *lines,
           f"小計: ¥{subtotal:,}"]
    if discount:
        out.append(f"値引 ({discount_pct:g}%): -¥{discount:,}")
    out.append(f"消費税 ({tax_pct:g}%): ¥{tax:,}")
    out.append(f"合計: ¥{total:,}")
    if skipped:
        out.append(f"（未登録のため除外: {', '.join(skipped)}）")
    return "\n".join(out)


def schedule_meeting(title: str = "", date: str = "", start_time: str = "",
                     duration_hours: float = 1, attendees=None,
                     description: str = "", confirm: bool = True) -> str:
    """Book a meeting in one call by default. With confirm=true it books a
    real event via the Google Calendar API; if calendar auth/creds are missing it
    degrades to a simulated confirmation so the workspace never breaks."""
    if not (title and date and start_time):
        return "[error] title / date / start_time を指定してください。"
    if isinstance(attendees, str):
        attendees = [a.strip() for a in attendees.split(",") if a.strip()]
    attendees = attendees or []
    who = f" / 参加者{len(attendees)}名" if attendees else ""
    dur = float(duration_hours or 1)
    agenda = f"\n議題: {description}" if description else ""

    if not confirm:
        return (f"【予定ドラフト（未確定）】「{title}」{date} {start_time} JST "
                f"／{dur:g}時間{who}{agenda}"
                "\n確定する場合は confirm=true で再度依頼してください。")

    try:
        from senpai.tools import gcal  # lazy: a missing google lib must not break import
        ok, link = gcal.create_event(
            title=title, date=date, start_time=start_time, duration_hours=dur,
            attendees=attendees, description=description,
        )
        if ok:
            tail = f"\n{link}" if link else ""
            return (f"【予定を登録しました】「{title}」{date} {start_time} JST "
                    f"／{dur:g}時間{who}{agenda}{tail}")
    except Exception:  # noqa: BLE001 — fall back to a simulated confirmation
        pass
    return (f"【予定を登録しました（シミュレーション）】「{title}」{date} {start_time} JST "
            f"／{dur:g}時間{who}{agenda}")


def send_email(to: str = "", subject: str = "", body: str = "") -> str:
    """Prepare an email draft. Never actually sends — human stays in the loop."""
    if not to:
        return "[error] 宛先 (to) を指定してください。"
    return (f"【メール下書き（送信はされません）】\n宛先: {to}\n件名: {subject}\n\n{body}")


_CALENDAR_CANNED = [
    "10:00 朝礼／案件確認",
    "13:00 顧客訪問（デモ）",
    "16:30 提案資料の作成",
]


def get_calendar(day: str = "today") -> str:
    """Today's (or a given day's) schedule. Simulated demo data."""
    d = config.today().isoformat() if str(day).lower() in ("today", "") else day
    return f"{d} の予定:\n- " + "\n- ".join(_CALENDAR_CANNED)


def search_knowledge(query: str = "", tags=None, limit: int = 4) -> str:
    """RAG over the validated knowledge corpus (principles + approved coaching
    items + playbook). Returns short, attributed/cited snippets to ground answers."""
    if isinstance(tags, str):
        tags = [tags]
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 4
    hits = _search_knowledge(query=query, tags=tags or [], limit=limit)
    from senpai.retrieval import trace as _trace
    _trace.record(
        "knowledge_keyword", scope="all", query=query,  # corpus is general, not per-account
        items=[{"id": kind, "customer": None, "score": int(score), "text": text}
               for score, kind, text in hits])
    if not hits:
        return ("該当する社内ナレッジが見つかりませんでした。"
                "route_to_expert の利用を検討してください。")
    lines = [f"[{kind}] {text}" for _score, kind, text in hits]
    return "社内ナレッジ:\n- " + "\n- ".join(lines)


def search_solutions(query: str = "", category: str = "", limit: int = 4) -> str:
    """Search Otsuka Shokai's real product/solution pages for what to offer a
    customer — named products/services (not internal category labels), each
    cited with its source URL. Prefer this over search_products when the rep
    needs a solution pitch/description, not a SKU price lookup."""
    from senpai.retrieval.solution_knowledge import search_solution_knowledge
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 4
    filters = {"category": category} if category else None
    hits = search_solution_knowledge(query, filters=filters, limit=limit)
    from senpai.retrieval import trace as _trace
    _trace.record(
        "solution_knowledge", scope="all", query=query,
        items=[{"id": h["solution"]["category"], "customer": None,
                "score": h["solution"]["relevance"], "text": h["solution"]["summary"]}
               for h in hits])
    if not hits:
        return "該当するソリューション・製品情報が見つかりませんでした。"
    lines = [f"[{h['solution']['category']}] {h['solution']['name']}: "
             f"{h['solution']['summary']}（出典: {h['solution']['source']}）"
             for h in hits]
    return "ソリューション・製品情報:\n- " + "\n- ".join(lines)


def search_notes(query: str = "", limit: int = 5, customer: str = "") -> str:
    """Semantic search over the field's daily reports (日報). Finds activities that
    *mean* the same thing as the query, not just share keywords — e.g. a search for
    『予算が理由で停滞』 surfaces 「コスト面で渋い」notes too. Returns dated, attributed
    snippets with their deal/customer + retrieval score so the rep can drill in.

    Grounding P0 — account scoping: pass `customer` (the account in focus) to
    restrict the search to that customer's own notes (the default for any
    account-specific question). If `customer` is omitted, we still try to detect a
    customer named in the query and scope to it; only when no account can be
    resolved do we fall back to a cross-account search (clearly labelled). A scoped
    search never widens to other customers."""
    from senpai.retrieval.semantic import semantic_search
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    # Clamp the result count: the notes are the bulk of the synthesis prompt AND of
    # what the model then quotes back, so an over-fetch (the model sometimes asks for
    # 10+) dominates Assistant latency at ~9 tok/s. The top semantically-ranked notes
    # carry the signal; the tail just lengthens the answer. Keep it tight.
    limit = max(1, min(limit, 6))

    # Resolve the account in focus: explicit arg first, then a customer named in the
    # query; None ⇒ no account resolved ⇒ cross-account fallback (preserves behavior).
    cust = None
    if customer:
        cust = store.resolve_customer(customer) or store.get_customer(customer)
    if not cust and query:
        cust = store.match_customer_in_text(query)
    cid = cust.get("customer_id") if cust else None

    from senpai.retrieval import semantic as _sem
    from senpai.retrieval import trace as _trace
    hits = semantic_search(query, corpus="activities", limit=limit, customer_id=cid)

    # Observability: record exactly what was retrieved (Retrieval Explorer spine).
    _trace.record(
        "notes_semantic",
        scope=(f"account:{cid}" if cid else "all"),
        query=query, mode=_sem.mode(),
        customer=(cust.get("name") if cust else None),
        items=[{"id": f"{h.get('deal_id', '-')}@{h.get('activity_date', '?')}",
                "customer_id": h.get("customer_id", ""),
                "customer": store.customer_name(h.get("customer_id", "")) or h.get("customer_id", ""),
                "score": round(float(h.get("score", 0)), 4),
                "text": h.get("snippet", "")} for h in hits])

    if not hits:
        if cid:
            return f"{cust.get('name', cid)} の日報で該当するものは見つかりませんでした。"
        return "該当する日報は見つかりませんでした。"

    scope = (f"（{cust.get('name')} に限定）" if cid
             else "（全社横断・特定顧客に絞れず）")
    lines = []
    for h in hits:
        cn = store.customer_name(h.get("customer_id", "")) or h.get("customer_id", "")
        lines.append(f"{h.get('activity_date', '?')}・{h.get('deal_id', '-')}（{cn}）"
                     f"[score {h.get('score', 0):.3f}]: {h.get('snippet', '')}")
    return f"関連する日報{scope}:\n- " + "\n- ".join(lines)


def query_graph(intent: str = "reps_who_win", category: str = "", industry: str = "",
                after_activity_type: str = "", customer: str = "", deal_id: str = "",
                entity_a: str = "", entity_b: str = "", limit: int = 8) -> str:
    """Multi-hop questions over the customer→deal→activity→rep→product graph.
    intent: 'reps_who_win' | 'account' | 'connections' | 'similar'."""
    from senpai.graph import query as gq
    from senpai.retrieval import trace as _trace
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 8
    # account intent is customer-scoped; the relational intents are cross-account
    # by design (and are research/manager-only per the governance table).
    _trace.record("graph", scope=(f"account:{customer}" if intent == "account" and customer else "all"),
                  intent=intent, query=" ".join(x for x in [category, industry, customer, deal_id] if x))

    if intent == "reps_who_win":
        rows = gq.reps_who_win(category=category, industry=industry,
                               after_activity_type=after_activity_type)[:limit]
        if not rows:
            return "条件に合う実績が見つかりませんでした。"
        cond = "／".join(x for x in [category, industry, after_activity_type] if x) or "全体"
        lines = [f"{r['rep_name']}（{r['rep_id']}）勝率{r['win_rate']*100:.0f}% "
                 f"（{r['won']}/{r['closed']}件）例: {', '.join(r['example_deal_ids'][:3])}"
                 for r in rows]
        return f"勝ちパターン分析【{cond}】:\n- " + "\n- ".join(lines)

    if intent == "account":
        g = gq.account_graph(customer)
        if g.get("status") != "found":
            return f"顧客「{customer}」は見つかりません。"
        reps = "、".join(r["name"] for r in g["reps"]) or "—"
        prods = "、".join(p["name"] for p in g["products"]) or "—"
        deals = "\n  ".join(f"{d['deal_id']} {d['name']}（{d['rank']}/{d['outcome']}・"
                            f"¥{d['amount']:,}）" for d in g["deals"][:limit]) or "—"
        return (f"{g['name']}（{g['industry']}/{g['size']}）の関係図:\n"
                f"担当: {reps}\n製品: {prods}\n案件:\n  {deals}")

    if intent == "connections":
        r = gq.connections(entity_a, entity_b)
        if r.get("status") != "found":
            return f"「{entity_a}」と「{entity_b}」を結ぶ経路は見つかりませんでした。"
        path = " → ".join(f"{n['label']}[{n['kind']}]" for n in r["path"])
        return f"{r['hops']}ホップの経路: {path}"

    if intent == "similar":
        rows = gq.similar_by_graph(deal_id, limit=limit)
        if not rows:
            return f"{deal_id} に関連する案件は見つかりませんでした。"
        lines = [f"{r['deal_id']} {r['name']}（{r['outcome']}・関連度{r['score']}）" for r in rows]
        return f"{deal_id} と関係の深い案件:\n- " + "\n- ".join(lines)

    return f"[error] 未知のintent: {intent}（reps_who_win/account/connections/similar）"


# ---------------------------------------------------------------------------
# Document generation — the chatbot's "do stuff" tools (PPTX / DOCX)
# ---------------------------------------------------------------------------
# Document tools build the file under config.GENERATED_DIR in one confirmed call,
# register it for download, and return a short confirmation. senpai.documents is
# imported lazily so a missing python-pptx/docx can never break tool import.
import hashlib as _hashlib

# Authored specs for the general tools, cached by request so repeated calls can reuse
# the same generated structure when the grounding is identical.
_GEN_SPEC_CACHE: dict[str, dict] = {}


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return "¥0"


def _deck_outline(slides: list[dict]) -> str:
    """Render a deck's headings + subheadings for the success message, so the rep
    sees the structure that was built (titles as headings, bullets/subtitle as
    sub-items) even though the file is generated directly."""
    lines: list[str] = []
    for i, s in enumerate(slides):
        lines.append(f"  {i + 1}. {s.get('title', '')}")
        subs = [str(b) for b in (s.get("bullets") or []) if str(b).strip()]
        if not subs and s.get("subtitle"):
            subs = [ln for ln in str(s["subtitle"]).splitlines() if ln.strip()]
        lines.extend(f"     - {b}" for b in subs)
    return "\n".join(lines)


def generate_proposal(deal_id: str = "", lang: str = "ja", confirm: bool = False) -> str:
    """4-slide PPTX sales proposal grounded in a deal's SPR data. Builds directly
    (no confirmation step) — the call commits the file in one round."""
    from senpai.documents import proposal, registry
    from senpai.documents.context import build_document_context
    if not deal_id:
        return "[error] deal_id を指定してください。"
    ctx = build_document_context(deal_id)
    if ctx is None:
        return f"案件 {deal_id} は見つかりません。"
    res = proposal.generate(deal_id, lang=lang)
    if res is None:
        return f"案件 {deal_id} は見つかりません。"
    files, _ctx, spec = res
    # Register the editable proposal PPTX (deal-scoped) plus its PDF and source HTML.
    registry.register("proposal", files["pptx"], deal_id=deal_id)
    formats = ["PPTX"]
    if files.get("pdf"):
        registry.register("pdf", files["pdf"], deal_id=deal_id)
        formats.append("PDF")
    if files.get("html"):
        registry.register("html", files["html"], deal_id=deal_id)
        formats.append("HTML")
    slides = spec.get("slides", [])
    outline = _deck_outline(slides)
    return (f"提案書({len(slides)}スライド、形式: {' / '.join(formats)})を生成しました"
            f"（{ctx.customer}様）。PowerPointで直接編集できます。\n構成:\n{outline}")


def generate_ringisho(deal_id: str = "", confirm: bool = True) -> str:
    """Formal 稟議書 DOCX (customer IT-manager -> CEO) grounded in deal data."""
    from senpai.documents import registry, ringisho
    from senpai.documents.context import build_document_context
    if not deal_id:
        return "[error] deal_id を指定してください。"
    ctx = build_document_context(deal_id)
    if ctx is None:
        return f"案件 {deal_id} は見つかりません。"
    if not confirm:
        pv = ctx.to_preview()
        pains = "、".join(pv["pain_points"]) or "（SPRに課題記録なし）"
        deal_label = (ctx.deal_name or ctx.customer) + (f"（{ctx.product_category}）" if ctx.product_category else "")
        return (f"【プレビュー】{ctx.customer}様 情報システム部の稟議書(DOCX)\n"
                f"- 対象案件: {ctx.deal_id} {deal_label}\n"
                f"- 背景・課題: {pains}\n"
                f"- 投資額: {_yen(pv['investment'])}\n"
                "- 構成: 背景・課題 / 提案内容 / 投資額と効果 / 結論・承認依頼\n"
                "【システム指示】プレビューが生成されました。これ以上ツールを呼び出さず、このプレビュー内容をユーザーに提示し、作成を実行してよいか確認してください。ユーザーが同意した場合のみ、次のターンで confirm=true に設定して再度呼び出してください。")
    res = ringisho.generate(deal_id)
    if res is None:
        return f"案件 {deal_id} は見つかりません。"
    path, _ctx = res
    rec = registry.register("ringisho", path, deal_id=deal_id)
    return f"稟議書(DOCX)を生成しました: {rec['filename']}（{ctx.customer}様）。"


# Conversation-grounding budget. RECENT_FLOOR snippets are always kept (immediate
# context — the current request and the tool result that just landed); the remaining
# slots up to MAX_SNIPPETS are filled by relevance to the request, not recency.
_CONVO_BUDGET = 4000
_CONVO_MAX_SNIPPETS = 8
_CONVO_RECENT_FLOOR = 3


def _truncate_on_boundary(text: str, limit: int) -> str:
    """Trim `text` to <= `limit` chars, cutting at the nearest natural boundary
    (snippet break → paragraph → line → sentence → word) instead of mid-string, so a
    fact — a company name, a quote figure — is never severed in half. A blind
    `text[:limit]` can drop the second half of '村田印刷' or '¥1,200,000'. Only honors
    a boundary that still keeps most of the budget; adds an elision marker."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    for sep in ("\n---\n", "\n\n", "\n", "。", ". ", "、", " "):
        cut = head.rfind(sep)
        if cut >= limit * 0.6:   # a break too early would waste most of the budget
            return head[:cut].rstrip() + " …"
    return head.rstrip() + " …"


# Latin/number words and CJK character bigrams. A script-agnostic stand-in for word
# segmentation so relevance scoring works WITHOUT a morphological analyzer (janome is
# only an optional dep, and its whitespace fallback can't split Japanese, which has no
# spaces). Bigrams give '村田印刷' the shared keys 村田/田印/印刷 across query & snippet.
_LATIN_NUM_RE = re.compile(r"[a-z0-9](?:[a-z0-9,.]*[a-z0-9])?")
_CJK_RUN_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿]+")


def _relevance_tokens(text: str) -> set[str]:
    text = (text or "").lower()
    toks = set(_LATIN_NUM_RE.findall(text))
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            toks.add(run)
        else:
            toks.update(run[i:i + 2] for i in range(len(run) - 1))
    return toks


def _snippet_relevance(query_tokens: set[str], text: str) -> float:
    """Relevance of a snippet to the current request: fraction of the request's
    content tokens it covers. 0.0 when there is no query signal or no overlap."""
    if not query_tokens:
        return 0.0
    toks = _relevance_tokens(text)
    if not toks:
        return 0.0
    return len(query_tokens & toks) / len(query_tokens)


def _conversation_grounding(prompt: str) -> str:
    """Context already established in this session — prior tool results (e.g. a
    workspace file we read) and assistant answers — so a doc that references 'the
    company/quote we just discussed' grounds on it instead of being invented. Reads
    the live conversation the chat loop publishes (senpai.tools.conversation).

    Kept compact: the doc author only needs the entity in focus and the facts around
    it, not the whole transcript. System messages and failed/empty tool results are
    dropped; the current request is included so intent is explicit.

    Selection is relevance-ranked, not just the tail — recency alone drops the entity
    in focus once a few turns intervene (a side question, extra tool calls), which is
    exactly the ungrounded-deck regression this grounding exists to prevent. The most
    recent RECENT_FLOOR snippets are always kept (immediate context); the rest of the
    budget goes to the OLDER snippets that best match the request. With no query
    signal it degrades to pure recency (the prior behavior)."""
    from senpai.tools import conversation as _conv
    convo = _conv.conversation()
    if not convo:
        return ""
    # (position, formatted-text), dropping system + failed/empty tool results.
    snippets: list[tuple[int, str]] = []
    for i, m in enumerate(convo):
        role, content = m.get("role"), m.get("content")
        if role == "system" or not isinstance(content, str) or not content.strip():
            continue
        if role == "tool":
            if content.startswith("[error]") or "見つかりません" in content:
                continue
            snippets.append((i, content.strip()))
        elif role == "assistant":
            snippets.append((i, content.strip()))
        elif role == "user":
            snippets.append((i, f"（依頼）{content.strip()}"))
    if not snippets:
        return ""

    query_tokens = _relevance_tokens(prompt)
    recent = {i for i, _ in snippets[-_CONVO_RECENT_FLOOR:]}
    older = [(i, t) for i, t in snippets if i not in recent]
    # Score each older snippet once; rank by relevance, then recency for ties.
    scored = sorted(
        ((_snippet_relevance(query_tokens, t), i, t) for i, t in older),
        key=lambda s: (s[0], s[1]), reverse=True)
    budget_n = max(0, _CONVO_MAX_SNIPPETS - len(recent))
    # Keep only older snippets that actually match the request; with no query signal
    # (query_tokens empty) fall back to recency so we never return nothing.
    keep_older = [(i, t) for score, i, t in scored[:budget_n]
                  if score > 0 or not query_tokens]
    chosen = sorted(
        [(i, t) for i, t in snippets if i in recent] + keep_older,
        key=lambda it: it[0])
    joined = "\n---\n".join(t for _, t in chosen)
    return _truncate_on_boundary(joined, _CONVO_BUDGET)


def _workspace_grounding(query: str) -> str:
    """Relevant LOCAL documents for `query`, or '' when nothing genuinely matched.
    Gated on a real filename/path match (score > 0), not the finder's recency
    fallback, so an unrelated deck ('best gaming laptops') isn't padded with random
    files. Read-only, sandboxed — the entity may live only in the rep's own files."""
    if not (query or "").strip():
        return ""
    try:
        from senpai.workspace import workspace_evidence
        from senpai.workspace.gather import _format
        res = workspace_evidence(query, limit=3)
    except Exception:  # noqa: BLE001 — grounding is best-effort
        return ""
    if not res.get("documents"):
        return ""
    if not any((f.get("score") or 0) > 0 for f in res.get("found", [])):
        return ""
    return _format(res)


def _gather_grounding(prompt: str, customer: str, use_web: bool) -> str:
    """Best-effort context for the general doc tools, gathered in priority order so
    the deck grounds on what the rep is actually referencing:
      1. the live conversation — a company/quote/deal discussed earlier this session
      2. the rep's own local documents (workspace) that match the topic
      3. internal CRM records for a named customer
      4. a live web_search (external/factual topics)
    Any layer may be empty (then the model uses general knowledge). Conversation and
    workspace come first because they carry the specific entity in focus — that is
    what stops a 'proposal for <company we just read from a file>' from being
    hallucinated as a generic deck under the wrong company name."""
    parts: list[str] = []

    convo_ctx = _conversation_grounding(prompt)
    if convo_ctx:
        parts.append(f"【これまでの会話・確定済みの文脈】\n{convo_ctx}")

    ws = _workspace_grounding(prompt or customer)
    if ws:
        parts.append(f"【ローカル文書（あなたのファイル）】\n{ws}")

    # CRM, in order of trust:
    #   1. an explicit customer arg — authoritative.
    #   2. the entity the conversation already RESOLVED (SessionFocus) — also
    #      authoritative: it comes from ids real tool results emitted (a deal we
    #      looked up, a customer we queried), so 'that company we discussed' is a
    #      lookup, not a re-inference. A deal in focus grounds on that specific deal.
    #   3. as a LAST resort, a fuzzy name match on the prompt — but only when the
    #      workspace didn't already pin the entity, since a local-file company must
    #      not pull an unrelated CRM customer (the wrong-company-name bug).
    cust = _resolve_customer(customer) if customer else None
    crm = ""
    if cust:
        crm = query_spr(customer=cust["customer_id"])
    else:
        focus = session_focus()
        if focus.deal_id:
            crm = query_spr(deal_id=focus.deal_id)
        elif focus.customer_id:
            crm = query_spr(customer=focus.customer_id)
        elif not ws:
            fuzzy = store.match_customer_in_text(prompt)
            if fuzzy:
                crm = query_spr(customer=fuzzy["customer_id"])
    if crm:
        parts.append(f"【社内データ】\n{crm}")

    if use_web:
        try:
            parts.append(f"【Web検索】\n{web_search(query=prompt)}")
        except Exception:  # noqa: BLE001 — grounding is best-effort
            pass
    return "\n\n".join(p for p in parts if p)


# External/factual cues in a free-prompt deck/doc — the topics that go stale in a
# model's weights (products, prices, "best-of" picks, current models, comparisons).
# When present, a general deck is grounded in a live web_search unless the caller
# says otherwise. Internal decks (a customer is named) ground in records instead.
_WEB_SIGNAL_RE = re.compile(
    r"best|top|latest|newest|current|cheap|price|budget|under|vs\b|versus|compare|"
    r"comparison|review|ranking|recommend|spec|market|trend|news|deal|20(2[3-9]|[3-9]\d)|"
    r"おすすめ|比較|最新|価格|相場|予算|以内|ランキング|レビュー|選び方|市場|"
    r"トレンド|ニュース|スペック|円",
    re.IGNORECASE,
)


def _auto_web(prompt: str) -> bool:
    """True when a free-prompt deck/doc should be web-grounded by default: the topic
    reads as external/factual/current, so the model's own knowledge is likely stale."""
    return bool(_WEB_SIGNAL_RE.search(prompt or ""))


def _resolve_use_web(use_web, prompt: str, customer: str) -> bool:
    """Decide grounding. Explicit True/False from the caller wins. When unspecified
    (None), auto-enable web for external/factual prompts, but not when the deck is
    scoped to a customer (that grounds in internal records instead)."""
    if use_web is not None:
        return bool(use_web)
    if customer:
        return False
    return _auto_web(prompt)


def _gen_key(kind: str, prompt: str, customer: str, use_web: bool, grounding: str = "") -> str:
    return _hashlib.md5(
        f"{kind}|{prompt}|{customer}|{use_web}|{grounding}".encode()).hexdigest()


def _author_spec(kind: str, prompt: str, customer: str, use_web: bool, lang: str):
    """Author (or reuse cached) a deck/doc spec for the general tools. None if the
    model is unavailable. The cache key includes the gathered grounding so the same
    prompt in a different conversation (different entity in focus) re-authors rather
    than returning a stale, differently-grounded deck."""
    from senpai.documents import author
    grounding = _gather_grounding(prompt, customer, use_web)
    key = _gen_key(kind, prompt, customer, use_web, grounding)
    spec = _GEN_SPEC_CACHE.get(key)
    if spec is not None:
        return spec
    spec = (author.author_deck if kind == "pptx" else author.author_doc)(
        prompt, grounding=grounding, lang=lang)
    if spec is not None:
        _GEN_SPEC_CACHE[key] = spec
    return spec


def generate_pptx(prompt: str = "", title: str = "", use_web=None,
                  customer: str = "", lang: str = "ja", confirm: bool = False) -> str:
    """General-purpose PPTX from a free prompt (LLM-authored). No fixed slide count.
    Builds directly (no confirmation step) — the call commits the file in one round.
    Grounding is automatic: external/factual topics are web-grounded by default; a
    named customer grounds it in internal records. Needs the model."""
    from senpai.documents import author, export, registry
    if not (prompt or "").strip():
        return "[error] プレゼンの主題(prompt)を指定してください。"
    if not author._use_llm():
        return "本機能はモデル(LLM)が必要です（SENPAI_USE_LLM=1 とモデルサーバ）。"
    spec = _author_spec("pptx", prompt, customer, _resolve_use_web(use_web, prompt, customer), lang)
    if spec is None:
        return "本機能はモデル(LLM)が必要です。現在モデルに接続できません。"
    slides = spec.get("slides", [])
    if title and slides:
        slides[0]["title"] = title
    slug = title or spec.get("_title") or prompt[:30]

    # HTML-first pipeline: build the deck as one self-contained HTML file (the visual
    # source of truth), then render a pixel-perfect PDF and an editable-text PPTX from it
    # with headless Chromium (native python-pptx fallback if the browser is unavailable).
    files = export.render_deck(spec, kind="pptx", slug=slug, lang=lang)
    formats = _register_deck_files(registry, files, primary_kind="pptx")

    outline = _deck_outline(slides)
    return (f"プレゼンを生成しました（{len(slides)}スライド、形式: {' / '.join(formats)}）。\n"
            f"PowerPointで直接編集できます。\n構成:\n{outline}")


def _register_deck_files(registry, files: dict, *, primary_kind: str) -> list[str]:
    """Register a deck's export set for download in a stable order — the editable office
    file first (the primary deliverable), then PDF, then the source HTML — so the primary
    is the one legacy single-document consumers pick up. Returns the format labels shown
    to the user (e.g. ['PPTX', 'PDF', 'HTML'])."""
    registry.register(primary_kind, files["pptx"])
    formats = [primary_kind.upper() if primary_kind in ("pptx", "docx") else "PPTX"]
    if files.get("pdf"):
        registry.register("pdf", files["pdf"])
        formats.append("PDF")
    if files.get("html"):
        registry.register("html", files["html"])
        formats.append("HTML")
    return formats


def generate_docx(prompt: str = "", title: str = "", use_web=None,
                  customer: str = "", lang: str = "ja", confirm: bool = True) -> str:
    """General-purpose DOCX from a free prompt (LLM-authored). Grounding is automatic:
    external/factual topics are web-grounded by default; a named customer grounds it
    in internal records. Needs the model."""
    from senpai.documents import author, registry
    from senpai.documents.render import output_path, render_docx
    if not (prompt or "").strip():
        return "[error] 文書の主題(prompt)を指定してください。"
    if not author._use_llm():
        return "本機能はモデル(LLM)が必要です（SENPAI_USE_LLM=1 とモデルサーバ）。"
    spec = _author_spec("docx", prompt, customer, _resolve_use_web(use_web, prompt, customer), lang)
    if spec is None:
        return "本機能はモデル(LLM)が必要です。現在モデルに接続できません。"
    sections = spec.get("sections", [])
    if not confirm:
        outline = "\n".join(f"  - {s.get('heading', '')}" for s in sections)
        return (f"【プレビュー】DOCX「{title or spec.get('_title') or prompt}」{len(sections)}セクション:\n"
                f"{outline}\n【システム指示】プレビューが生成されました。これ以上ツールを呼び出さず、このプレビュー内容をユーザーに提示し、作成を実行してよいか確認してください。ユーザーが同意した場合のみ、次のターンで confirm=true に設定して再度呼び出してください。")
    if title:
        spec["title"] = title
    path = output_path("docx", title or spec.get("_title") or prompt[:30], "docx")
    render_docx(spec, path)
    rec = registry.register("docx", path)
    return f"文書(DOCX)を生成しました: {rec['filename']}（{len(sections)}セクション）。"


# ---------------------------------------------------------------------------
# Dispatch (mirrors demo/tools.py)
# ---------------------------------------------------------------------------
def segment_intelligence(query: str = "", category: str = "", industry: str = "",
                         outcome: str = "all", limit: int = 6) -> str:
    """Aggregate/thematic answers across category×industry market segments — win
    rates, common failure modes, recommended plays — grounded in the deal-health
    engine and citing evidence deal ids. GPU-free (committed reports or in-memory
    deterministic build)."""
    from senpai.graph import communities
    from senpai.retrieval import trace as _trace
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 6
    reports = communities.select(query=query, category=category, industry=industry,
                                 outcome=outcome, limit=limit)
    _trace.record("segment_intelligence", scope="all",
                  items=[{"id": r["id"], "score": r.get("win_rate")} for r in reports],
                  query=" ".join(x for x in [query, category, industry] if x), n=len(reports))
    if not reports:
        return "該当するセグメント（カテゴリ×業界）が見つかりませんでした。"
    return "\n\n".join(communities.format_report(r) for r in reports)


def search_workspace_documents(query: str = "", limit: int = 0) -> str:
    """Find and read relevant LOCAL documents (PDF/DOCX/PPTX/XLSX/TXT/MD) from the
    sandboxed workspace, returning their text with per-file citations. Runs on the
    orchestration engine: one `find` fans out into parallel `extract` tasks. READ-ONLY.
    The chat loop's synthesis round reduces the returned documents into the answer."""
    from senpai.retrieval import trace as _trace
    from senpai.workspace import workspace_evidence
    lim = None
    try:
        lim = int(limit) if limit else None
    except (TypeError, ValueError):
        lim = None
    res = workspace_evidence(query, limit=lim)
    _trace.record("workspace", scope="local_files",
                  items=[{"id": d["rel"], "score": d.get("chars")} for d in res["documents"]],
                  query=query, n=len(res["documents"]))
    from senpai.workspace.gather import _format
    return _format(res)


def edit_workspace_document(path: str, content: str, confirm: bool = True) -> str:
    """Modifies or creates a local text document in the workspace.
    Commits by default; callers may pass confirm=False only for an explicit preview.
    """
    from senpai.workspace import sandbox
    try:
        safe_p = sandbox.safe_path(path)
    except sandbox.SandboxError as e:
        return f"エラー: パスが無効または境界外です ({e})"
    
    if safe_p.suffix.lower() not in (".txt", ".md", ".json", ".csv"):
        return f"エラー: テキストファイル（.txt, .md, .json, .csv等）のみ編集可能です。指定された拡張子: {safe_p.suffix}"
    
    if not confirm:
        return (f"【ファイル編集プレビュー（保存されていません）】\n"
                f"対象: {sandbox.rel(safe_p)}\n"
                f"新しい内容:\n{content}\n\n"
                f"よろしければ確認して「保存して」と指示してください（confirm=True を指定して再実行します）。")
    
    try:
        safe_p.parent.mkdir(parents=True, exist_ok=True)
        safe_p.write_text(content, encoding="utf-8")
        from senpai.retrieval import trace as _trace
        _trace.record("workspace_edit", scope="local_files",
                      items=[{"id": sandbox.rel(safe_p), "score": len(content)}],
                      query=path, n=1)
        return f"ファイル {sandbox.rel(safe_p)} を保存しました。"
    except Exception as e:
        return f"ファイルの保存中にエラーが発生しました: {e}"


def move_workspace_document(src: str, dst: str, confirm: bool = True) -> str:
    """Move or rename a local document in the workspace.
    Commits by default; callers may pass confirm=False only for an explicit preview.
    """
    from senpai.workspace import sandbox
    try:
        s = sandbox.safe_path(src)
        d = sandbox.safe_path(dst)
    except sandbox.SandboxError as e:
        return f"エラー: パスが無効または境界外です ({e})"
    
    if not s.exists():
        return f"エラー: 移動元のファイルが存在しません: {src}"
    
    if not confirm:
        return (f"【ファイル移動プレビュー（実行されていません）】\n"
                f"移動元: {sandbox.rel(s)}\n"
                f"移動先: {sandbox.rel(d)}\n\n"
                f"よろしければ確認して「移動して」と指示してください（confirm=True を指定して再実行します）。")
    
    try:
        new_path = sandbox.move_within(src, dst)
        from senpai.retrieval import trace as _trace
        _trace.record("workspace_move", scope="local_files",
                      items=[{"id": new_path, "score": 1}],
                      query=f"{src} -> {dst}", n=1)
        return f"ファイルを移動しました: {sandbox.rel(s)} -> {new_path}"
    except Exception as e:
        return f"ファイルの移動中にエラーが発生しました: {e}"


def advise_solutions(customer: str = "", deal_id: str = "") -> str:
    """Recommend appropriate Otsuka solutions for a customer based on their context.
    Uses expansion signals, environment gaps, and category matching to generate
    deterministic candidates, then explains why they fit."""
    from senpai.recommendation.run import run_solution_advisor
    cid = ""
    if customer:
        c = _resolve_customer(customer)
        if c:
            cid = c["customer_id"]
        else:
            cid = customer
            
    recs = run_solution_advisor(cid, deal_id)
    if not recs:
        return "提案できるソリューションが見つかりませんでした。"
        
    lines = []
    for r in recs:
        lines.append(f"■ {r.solution_name} ({r.category}) - 適合度: {r.match_score:.2f}, 確信度: {r.confidence:.2f}")
        lines.append(f"  理由: {r.why}")
        if r.business_value:
            lines.append(f"  価値: {r.business_value}")
        if r.risks:
            lines.append(f"  リスク: {', '.join(r.risks)}")
        if r.complementary_solutions:
            lines.append(f"  関連: {', '.join(r.complementary_solutions)}")
        if r.product_pages:
            pages = ", ".join(f"[{p.get('title')}]({p.get('url')})" for p in r.product_pages)
            lines.append(f"  詳細: {pages}")
        lines.append("")
        
    return "推奨ソリューション:\n\n" + "\n".join(lines)



_DISPATCH = {
    "query_spr": query_spr,
    "find_deals": find_deals,
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
    "morning_briefing": morning_briefing,
    "list_at_risk_deals": list_at_risk_deals,
    "team_pipeline_overview": team_pipeline_overview,
    "team_report_digest": team_report_digest,
    "rep_coaching_focus": rep_coaching_focus,
    "draft_message": draft_message,
    "web_search": web_search,
    "web_research": web_research,
    # Sales demo tools (ported from demo/tools.py, re-grounded on the store)
    "search_products": search_products,
    "create_quote": create_quote,
    "schedule_meeting": schedule_meeting,
    "send_email": send_email,
    "get_calendar": get_calendar,
    "search_knowledge": search_knowledge,
    "search_solutions": search_solutions,
    "search_notes": search_notes,
    "query_graph": query_graph,
    "segment_intelligence": segment_intelligence,
    "search_workspace_documents": search_workspace_documents,
    "edit_workspace_document": edit_workspace_document,
    "move_workspace_document": move_workspace_document,
    # Document generation (the chatbot's "do stuff" tools)
    "generate_proposal": generate_proposal,
    "generate_ringisho": generate_ringisho,
    "generate_pptx": generate_pptx,
    "generate_docx": generate_docx,
    "advise_solutions": advise_solutions,
}


_ALWAYS_CONFIRM_TOOLS = {
    "schedule_meeting",
    "edit_workspace_document",
    "move_workspace_document",
    "generate_proposal",
    "generate_ringisho",
    "generate_pptx",
    "generate_docx",
}


def _force_confirm_true(name: str, arguments: dict) -> dict:
    """Commit confirmation-gated tools in one call.

    The assistant prompt asks the model to pass confirm=True, but tool correctness
    should not depend on the model remembering that detail. Keep the coercion in the
    shared dispatch path so API chat, tests, and any future caller get the same
    behavior.
    """
    if name not in _ALWAYS_CONFIRM_TOOLS:
        return arguments
    coerced = dict(arguments)
    coerced["confirm"] = True
    return coerced


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
    arguments = _force_confirm_true(name, arguments)
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
        ("find_deals", {"product_category": "サーバー", "size": "中規模", "outcome": "won", "limit": 5}),
        ("find_similar_deals", {"customer": "C01"}),
        ("retrieve_playbook", {"query": "お客様が決定を先延ばし", "tags": ["決定先延ばし"]}),
        ("search_notes", {"query": "予算が厳しく決裁が止まっている", "limit": 3}),
        ("lookup_customer_environment", {"customer": "C01"}),
        ("get_product_info", {"product": "MFP30"}),
        ("score_deal_health", {"deal_id": "D001"}),
        ("review_sales_note", {"note": "お客様は社内で検討してから連絡するとのこと。"}),
        ("draft_daily_report", {"activity": "アクメ商事を訪問しデモを実施", "deal_id": "D001"}),
        ("route_to_expert", {"question": "ネットワーク更改の構成相談", "tags": ["ネットワーク"]}),
        ("summarize_reports", {"rep_id": "R05"}),
        ("get_seasonal_context", {"month": 2}),
        ("morning_briefing", {"rep_id": "R12", "limit": 5}),
        ("list_at_risk_deals", {"limit": 5}),
        ("query_graph", {"intent": "reps_who_win", "category": "サーバー"}),
        ("query_graph", {"intent": "account", "customer": "C28"}),
        ("segment_intelligence", {"query": "製造業のサーバー案件はなぜ負ける？", "outcome": "lost"}),
        ("segment_intelligence", {"query": "どのカテゴリの勝率が低い？"}),
        ("team_pipeline_overview", {}),
        ("team_report_digest", {}),
        ("rep_coaching_focus", {}),
        ("draft_message", {"to": "伊藤さん", "about": "D003の進捗", "deal_id": "D003"}),
        ("web_search", {"query": "製造業 IT投資 動向"}),
        # Document tools: preview (no file) is deterministic; the grounded build is
        # GPU-free, the general tools need a model so they print their guard message.
        ("generate_proposal", {"deal_id": "D001"}),
        ("generate_proposal", {"deal_id": "D001", "confirm": True}),
        ("generate_ringisho", {"deal_id": "D001", "confirm": True}),
        ("generate_pptx", {"prompt": "GTA 6 の発売展望", "use_web": False}),
        ("generate_docx", {"prompt": "社内向けセキュリティ研修の概要"}),
    ]:
        print(f"\n### {n}({a})\n{dispatch(n, a)}")
