"""Multi-agent crew — three specialists analyse one deal together.

This is the "not a chatbot" surface: instead of one model answering, a small crew
of role-specialised agents work a single deal and the rep watches them do it.

  🔍 Researcher (リサーチャー) — gathers the grounded facts: the deal snapshot,
     comparable won deals, related daily-report risk signals, the IT environment.
  🩺 Coach (コーチ) — reads the deal's health: risk band, the specific signals,
     what the rep should be careful about.
  ♟️ Strategist (ストラテジスト) — merges the Researcher's facts and the Coach's
     read into an actionable plan: talking points, objection handling, next move.

Researcher and Coach are independent, so they run in PARALLEL on worker threads;
the Strategist depends on both and runs once they finish. Each agent's tool calls
and its written contribution stream to the UI as they happen (via a shared queue),
so the rep sees a team working — not a single reply appearing.

Every fact comes from the deterministic store / scoring engine through the existing
tool impls; only each agent's prose is LLM-written. No numbers are invented.
"""
from __future__ import annotations

import queue
import re
import threading
import time
from typing import Callable, Iterator

from senpai.data import store
from senpai.health.scoring import score_deal
from senpai.llm import client
from senpai.tools import impl

# The crew roster — sent to the UI first so it can lay out one lane per agent.
AGENTS = [
    {"id": "researcher", "label": "リサーチャー", "role": "事実収集", "emoji": ""},
    {"id": "coach", "label": "コーチ", "role": "健全性診断", "emoji": ""},
    {"id": "strategist", "label": "ストラテジスト", "role": "戦略立案", "emoji": ""},
]

_RESEARCHER_SYS = (
    "あなたは大塚商会の営業チームのリサーチャーです。与えられた社内データ（案件情報・"
    "類似事例・日報・IT環境）だけを根拠に、この商談の事実関係を簡潔に整理します。"
    "推測や創作は禁止。金額・日付・固有名詞はデータのとおりに引用してください。"
)
_COACH_SYS = (
    "あなたは大塚商会のベテラン営業コーチです。健全性スコアとリスク信号を読み解き、"
    "この商談で担当者が見落としがちな点・リスクの本質を、根拠とともに簡潔に指摘します。"
)
_STRATEGIST_SYS = (
    "あなたは大塚商会の営業戦略家です。リサーチャーの事実とコーチの診断を統合し、"
    "次の打ち合わせに向けた具体的で実行可能な作戦を立てます。指定のMarkdown構成で出力。"
)

# A tool-call callback: each agent reports the tools it runs so the lane shows them.
Emit = Callable[[dict], None]


def _run_researcher(d: dict, customer: str, emit: Emit) -> tuple[str, dict]:
    deal_id = d["deal_id"]
    cust = store.get_customer(d["customer_id"]) or {}
    industry = cust.get("industry", "")

    snapshot = impl.query_spr(deal_id=deal_id)
    emit({"type": "agent_tool", "agent_id": "researcher", "name": "query_spr",
          "summary": f"{deal_id} の案件サマリーと直近活動"})
    comparables = impl.find_similar_deals_tool(customer=customer, industry=industry)
    emit({"type": "agent_tool", "agent_id": "researcher", "name": "find_similar_deals",
          "summary": "類似の成約事例を照合"})
    notes = impl.search_notes(customer=customer, query="課題 リスク 懸念 予算 決裁", limit=4)
    emit({"type": "agent_tool", "agent_id": "researcher", "name": "search_notes",
          "summary": "関連する日報の課題シグナル"})
    env = impl.lookup_customer_environment(customer=customer)
    emit({"type": "agent_tool", "agent_id": "researcher", "name": "lookup_customer_environment",
          "summary": "顧客のIT環境"})

    grounding = (f"【案件】\n{snapshot}\n\n【類似事例】\n{comparables}\n\n"
                 f"【日報の課題】\n{notes}\n\n【IT環境】\n{env}")
    contribution = client.simple_complete(
        [{"role": "system", "content": _RESEARCHER_SYS},
         {"role": "user", "content":
             f"対象: {customer} / {d.get('deal_name', '')}\n\n"
             "以下の社内データだけを根拠に、この商談の事実関係を3〜5個の箇条書きで"
             f"簡潔に整理してください。\n\n{grounding}"}],
        no_think=True, max_tokens=400)
    return contribution, {"snapshot": snapshot, "comparables": comparables,
                          "notes": notes, "env": env}


def _run_coach(d: dict, customer: str, emit: Emit) -> tuple[str, dict]:
    deal_id = d["deal_id"]
    health = impl.score_deal_health(deal_id=deal_id)
    emit({"type": "agent_tool", "agent_id": "coach", "name": "score_deal_health",
          "summary": "健全性スコアとリスク信号"})

    res = score_deal(d, store.activities_for_deal(deal_id))
    reasons = res.top_reasons(5)
    reason_block = "\n".join(f"- {r}" for r in reasons) or "- 目立った信号なし"
    contribution = client.simple_complete(
        [{"role": "system", "content": _COACH_SYS},
         {"role": "user", "content":
             f"対象: {customer} / {d.get('deal_name', '')}\n\n"
             f"健全性: {health}\n\nリスク要因:\n{reason_block}\n\n"
             "この商談で担当者が特に注意すべき点とリスクの本質を、3点以内で"
             "簡潔に指摘してください。"}],
        no_think=True, max_tokens=350)
    return contribution, {"health": health, "reasons": reasons}


def _run_strategist(d: dict, customer: str, researcher_md: str, coach_md: str) -> str:
    return client.simple_complete(
        [{"role": "system", "content": _STRATEGIST_SYS},
         {"role": "user", "content":
             f"対象商談: {customer} / {d.get('deal_name', '')}"
             f"（{d.get('product_category', '')}）\n\n"
             f"【リサーチャーの所見】\n{researcher_md}\n\n"
             f"【コーチの診断】\n{coach_md}\n\n"
             "上記を統合し、次の打ち合わせに向けた作戦を以下のMarkdown構成でまとめてください。\n"
             "### トークの要点\n（3点・箇条書き）\n"
             "### 想定される反論と切り返し\n（2点・箇条書き）\n"
             "### 次の一手\n（1〜2個の具体的アクション）"}],
        no_think=True, max_tokens=1200)  # the user-facing brief — must not truncate


def _worker(agent_id: str, run: Callable[[Emit], tuple[str, dict]],
            q: "queue.Queue", results: dict) -> None:
    """Run one independent agent on its own thread, streaming its lifecycle to the
    shared queue. `run(emit)` returns (contribution, facts). Used for both the deal
    crew (Researcher/Coach) and the manager fan-out (one analyst per rep)."""
    t0 = time.time()
    q.put({"type": "agent", "id": agent_id, "status": "running"})
    try:
        contribution, facts = run(lambda ev: q.put(ev))
        results[agent_id] = (contribution, facts)
        q.put({"type": "agent", "id": agent_id, "status": "done",
               "contribution": contribution, "elapsed": round(time.time() - t0, 1)})
    except Exception as e:  # noqa: BLE001 — one agent failing must not kill the crew
        results[agent_id] = (f"（{agent_id} は分析を完了できませんでした: {e}）", {})
        q.put({"type": "agent", "id": agent_id, "status": "error", "reason": str(e),
               "elapsed": round(time.time() - t0, 1)})
    finally:
        q.put({"type": "_worker_done", "id": agent_id})


def _drain_parallel(q: "queue.Queue", n_workers: int) -> Iterator[dict]:
    """Yield every streamed event from `n_workers` agent threads until all finish."""
    finished = 0
    while finished < n_workers:
        ev = q.get()
        if ev.get("type") == "_worker_done":
            finished += 1
            continue
        yield ev


def run_crew(deal_id: str) -> Iterator[dict]:
    """Stream a full multi-agent analysis of one deal as typed event dicts:
      crew      — the roster (one lane per agent), with the deal in focus
      agent     — an agent's status: running | done | error (+ contribution on done)
      agent_tool— a tool an agent ran (name + human summary)
      final     — the Strategist's merged brief (Markdown)
      done      — terminal
    Researcher + Coach run in parallel; Strategist runs after both."""
    d = store.get_deal(deal_id)
    if not d:
        yield {"type": "error", "reason": "deal_not_found"}
        return
    customer = store.customer_name(d["customer_id"])
    yield {"type": "crew", "deal_id": deal_id, "customer": customer,
           "deal_name": d.get("deal_name") or customer,
           "product_category": d.get("product_category", ""),
           "agents": AGENTS}

    q: "queue.Queue" = queue.Queue()
    results: dict[str, tuple[str, dict]] = {}
    threads = [
        threading.Thread(target=_worker, args=(
            "researcher", lambda emit: _run_researcher(d, customer, emit), q, results), daemon=True),
        threading.Thread(target=_worker, args=(
            "coach", lambda emit: _run_coach(d, customer, emit), q, results), daemon=True),
    ]
    for t in threads:
        t.start()
    yield from _drain_parallel(q, len(threads))

    # Both fact-gatherers are done — the Strategist synthesises over their findings.
    yield {"type": "agent", "id": "strategist", "status": "running"}
    t0 = time.time()
    researcher_md = results.get("researcher", ("", {}))[0]
    coach_md = results.get("coach", ("", {}))[0]
    try:
        final_md = _run_strategist(d, customer, researcher_md, coach_md)
    except Exception as e:  # noqa: BLE001
        yield {"type": "agent", "id": "strategist", "status": "error", "reason": str(e)}
        yield {"type": "done"}
        return
    yield {"type": "agent", "id": "strategist", "status": "done",
           "contribution": final_md, "elapsed": round(time.time() - t0, 1)}
    yield {"type": "final", "markdown": final_md}
    yield {"type": "done"}


# --- Manager fan-out: one analyst agent per rep, in parallel -----------------
_REP_ANALYST_SYS = (
    "あなたは大塚商会の営業マネージャーを補佐するアナリストです。担当者一人の"
    "パイプライン概況と要注意案件を読み、マネージャーが今週コーチングで重点を置く"
    "べき点を、具体的な案件IDを挙げて簡潔に示します。推測や創作は禁止。"
)
_TEAM_LEAD_SYS = (
    "あなたは大塚商会の営業マネージャーです。各担当のアナリスト所見を統合し、"
    "チーム全体で今週優先すべきアクションを、指定のMarkdown構成で簡潔にまとめます。"
)


def _rep_roster(limit: int = 5) -> list[str]:
    """Reps with open deals, ranked by risk exposure (most red deals first, then
    pipeline size) — the manager's attention should fan out to them in that order."""
    by_rep: dict[str, list] = {}
    for d, res, _flags in impl._score_open_deals():
        by_rep.setdefault(store.deal_rep_id(d), []).append((d, res))
    ranked = sorted(
        by_rep.items(),
        key=lambda kv: (sum(1 for _, r in kv[1] if r.band == "red"), len(kv[1])),
        reverse=True)
    return [rid for rid, _ in ranked[:limit] if rid]


def _run_rep_analyst(rep_id: str, emit: Emit) -> tuple[str, dict]:
    name = store.rep_name(rep_id)
    pipeline = impl.team_pipeline_overview(rep_id=rep_id)
    emit({"type": "agent_tool", "agent_id": rep_id, "name": "team_pipeline_overview",
          "summary": f"{name} のパイプライン概況"})
    at_risk = impl.list_at_risk_deals(rep_id=rep_id, band="yellow", limit=5)
    emit({"type": "agent_tool", "agent_id": rep_id, "name": "list_at_risk_deals",
          "summary": "要注意案件の抽出"})
    contribution = client.simple_complete(
        [{"role": "system", "content": _REP_ANALYST_SYS},
         {"role": "user", "content":
             f"担当: {name}\n\n【パイプライン】\n{pipeline}\n\n【要注意案件】\n{at_risk}\n\n"
             "この担当者について、マネージャーが今週コーチングで重点を置くべき点を"
             "2〜3点、具体的な案件IDを挙げて簡潔にまとめてください。"}],
        no_think=True, max_tokens=300)
    return contribution, {"pipeline": pipeline, "at_risk": at_risk}


def _run_team_lead(cards: dict[str, str]) -> str:
    joined = "\n\n".join(f"【{store.rep_name(rid)}】\n{md}" for rid, md in cards.items())
    return client.simple_complete(
        [{"role": "system", "content": _TEAM_LEAD_SYS},
         {"role": "user", "content":
             f"各担当アナリストの所見:\n\n{joined}\n\n"
             "チーム全体で、マネージャーが今週優先すべきアクションを以下の構成でまとめてください。\n"
             "### 🚩 最優先（今日対応）\n（1〜2件・担当と案件IDを明記）\n"
             "### 📋 今週のコーチング重点\n（2〜3点）\n"
             "### 💪 良い兆候\n（1点）"}],
        no_think=True, max_tokens=1200)  # the user-facing brief — must not truncate


def run_team(limit: int = 5) -> Iterator[dict]:
    """Stream a manager fan-out: one analyst agent per rep runs in PARALLEL, each
    producing a coaching card for that rep; then the manager (team lead) synthesises
    a prioritised action list. Same event contract as run_crew — `agents` is dynamic
    (one lane per rep) and the merged plan lands in `final`."""
    reps = _rep_roster(limit)
    if not reps:
        yield {"type": "error", "reason": "no_reps"}
        return
    yield {"type": "crew", "mode": "team",
           "agents": [{"id": rid, "label": store.rep_name(rid), "role": "担当分析", "emoji": "👤"}
                      for rid in reps]}

    q: "queue.Queue" = queue.Queue()
    results: dict[str, tuple[str, dict]] = {}
    threads = [
        threading.Thread(target=_worker, args=(
            rid, (lambda r: lambda emit: _run_rep_analyst(r, emit))(rid), q, results), daemon=True)
        for rid in reps
    ]
    for t in threads:
        t.start()
    yield from _drain_parallel(q, len(threads))

    # All rep analysts done — the manager prioritises across the team.
    t0 = time.time()
    try:
        final_md = _run_team_lead({rid: results.get(rid, ("", {}))[0] for rid in reps})
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "reason": str(e)}
        yield {"type": "done"}
        return
    yield {"type": "final", "markdown": final_md, "elapsed": round(time.time() - t0, 1)}
    yield {"type": "done"}


def _key_deal_for_customer(cid: str) -> dict | None:
    """The deal a rep most needs to prep for: worst-health OPEN deal, else any deal."""
    open_scored = [(d, res) for d, res, _ in impl._score_open_deals() if d["customer_id"] == cid]
    if open_scored:
        return max(open_scored, key=lambda t: t[1].score)[0]
    deals = store.deals_for_customer(cid)
    return deals[0] if deals else None


def resolve_crew_target(query: str) -> dict:
    """Resolve a typed `/crew fujimoto` (customer name, romaji, or deal id) to the
    one deal the crew should analyse — PRESERVING ambiguity as a first-class state,
    exactly like the chat/research resolvers. Returns one of:
      {"status": "resolved",  "deal_id", "customer"}
      {"status": "ambiguous", "candidates": [{customer_id, name, deal_id}]}
      {"status": "not_found"}
    An explicit deal id wins; a unique customer resolves to their key deal; a vague
    stem ('fujimoto' → several 藤本 companies) surfaces the same picker the user
    already knows, so the rep chooses instead of the system guessing."""
    q = (query or "").strip()
    m = re.search(r"\bD\d{3,}\b", q, re.IGNORECASE)
    if m:
        d = store.get_deal(m.group(0).upper())
        if d:
            return {"status": "resolved", "deal_id": d["deal_id"],
                    "customer": store.customer_name(d["customer_id"])}

    cust = store.match_customer_in_text(q)
    if cust:
        d = _key_deal_for_customer(cust["customer_id"])
        if d:
            return {"status": "resolved", "deal_id": d["deal_id"],
                    "customer": store.customer_name(cust["customer_id"])}
        return {"status": "not_found"}

    amb = store.ambiguous_match_in_text(q)
    if amb:
        candidates = []
        for c in amb:
            d = _key_deal_for_customer(c["customer_id"])
            candidates.append({"customer_id": c["customer_id"], "name": c.get("name", ""),
                               "deal_id": d["deal_id"] if d else None})
        # The matched stem (longest ambiguous alias actually present) — shown in the
        # picker instead of the whole "/crew plan me a meet with fujimoto" sentence.
        low = q.lower()
        stem = max((k for k, ids in store._alias_index().items()
                    if len(ids) > 1 and store._key_in_text(k, low)),
                   key=len, default=q)
        return {"status": "ambiguous", "stem": stem, "candidates": candidates}

    return {"status": "not_found"}
