"""Offline feasibility eval for an Atlas-style intent router.

Tests the hypothesis from docs (intent_router recommendation): can a *lightweight*
embedding classifier — the project's existing multilingual MiniLM (no GPU, no LLM
call) — reliably route a request on three orthogonal heads:

  * destination : research | tool | chat
  * tool_hint   : which tool (only for destination == tool)
  * mode        : fast | think   (reasoning-mode prior)

It trains tiny LogisticRegression heads on MiniLM embeddings and reports
cross-validated accuracy, then compares the destination + mode heads against the
CURRENT rule baselines (_is_research_intent, DeterministicReasoningRouter) so we
can see whether the classifier actually beats the rules before wiring anything in.

Run once:  python scripts/eval_intent_router.py
Needs only fastembed + sklearn + numpy (all already installed). No LLM endpoint.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root → import senpai

import numpy as np
from collections import Counter

# --- labeled dataset --------------------------------------------------------
# (query, destination, tool_hint, mode). Real store customers used in research /
# customer rows so the rule baseline (_is_research_intent) gets a fair shot.
# tool_hint is "" when destination != "tool". JA-heavy with EN mixed in, mirroring
# the real bilingual traffic.
DATA: list[tuple[str, str, str, str]] = [
    # ---- research (customer-research skill → research_stream) ----
    ("丸三食品について教えて", "research", "", "fast"),
    ("株式会社松田サービスの背景を調べて", "research", "", "fast"),
    ("村田印刷のことを教えて", "research", "", "fast"),
    ("青木事務所について知りたい", "research", "", "fast"),
    ("豊田建設の情報を教えて", "research", "", "fast"),
    ("Tell me about 丸三食品", "research", "", "fast"),
    ("research 株式会社松田サービス", "research", "", "fast"),
    ("あけぼの商事の最近の動きを調べて", "research", "", "fast"),
    ("background on Murata Printing", "research", "", "fast"),
    ("近藤電機についてリサーチして", "research", "", "fast"),
    ("D027の案件背景を調べたい", "research", "", "fast"),
    ("江口電機の会社概要を教えて", "research", "", "fast"),

    # ---- tool: schedule_meeting ----
    ("明日15時に会議を設定して", "tool", "schedule_meeting", "fast"),
    ("丸三食品と来週月曜10時にミーティングを入れて", "tool", "schedule_meeting", "fast"),
    ("setup a meeting with microsoft 5pm today", "tool", "schedule_meeting", "fast"),
    ("打ち合わせを金曜の午後に予約して", "tool", "schedule_meeting", "fast"),
    ("schedule a 1 hour call tomorrow morning", "tool", "schedule_meeting", "fast"),
    # ---- tool: send_email ----
    ("伊藤さんにお礼のメールを下書きして", "tool", "send_email", "fast"),
    ("draft an email to the client about the quote", "tool", "send_email", "fast"),
    ("見積送付のメール文面を作って", "tool", "send_email", "fast"),
    ("フォローアップのメールを準備して", "tool", "send_email", "fast"),
    # ---- tool: create_quote ----
    ("MFP30を2台で見積を作って", "tool", "create_quote", "fast"),
    ("ノートPC8台の見積を10%引きで出して", "tool", "create_quote", "fast"),
    ("quote 3 servers for Acme", "tool", "create_quote", "fast"),
    ("サーバー1台分の見積書を作成して", "tool", "create_quote", "fast"),
    # ---- tool: web_search ----
    ("今日の東京の天気は？", "tool", "web_search", "fast"),
    ("最新のWindows Server の価格を調べて", "tool", "web_search", "fast"),
    ("USDからJPYのレートは今いくら？", "tool", "web_search", "fast"),
    ("search the web for NAS market trends 2026", "tool", "web_search", "fast"),
    ("競合の新製品のニュースを調べて", "tool", "web_search", "fast"),
    # ---- tool: route_to_expert ----
    ("ネットワーク構成について専門家に相談したい", "tool", "route_to_expert", "fast"),
    ("この案件、詳しい先輩に繋いでほしい", "tool", "route_to_expert", "fast"),
    ("サーバー移行は自信がないので専門家を紹介して", "tool", "route_to_expert", "fast"),
    # ---- tool: query_spr (record lookup) ----
    ("D001の案件状況を見せて", "tool", "query_spr", "fast"),
    ("丸三食品の案件一覧を出して", "tool", "query_spr", "fast"),
    ("show the deals for customer C28", "tool", "query_spr", "fast"),
    # ---- tool: score_deal_health (numeric → think) ----
    ("D027の健全度は？", "tool", "score_deal_health", "think"),
    ("この案件のリスクスコアを評価して", "tool", "score_deal_health", "think"),
    ("how healthy is deal D005?", "tool", "score_deal_health", "think"),
    # ---- tool: search_products / get_product_info ----
    ("20万円以下のノートPCを探して", "tool", "search_products", "fast"),
    ("Color MFP 3000のスペックと価格は？", "tool", "get_product_info", "fast"),
    ("A3対応のプリンタを一覧で", "tool", "search_products", "fast"),
    # ---- tool: search_knowledge / retrieve_playbook (coaching "how do I") ----
    ("決裁者に会えないときどう対応すべき？", "tool", "search_knowledge", "think"),
    ("値引きを求められたときの進め方を教えて", "tool", "search_knowledge", "think"),
    ("競合と比較されている案件の打ち手は？", "tool", "retrieve_playbook", "think"),
    # ---- tool: list_at_risk_deals (manager synthesis → think) ----
    ("危ない案件を一覧にして", "tool", "list_at_risk_deals", "think"),
    ("今リスクの高い案件は？", "tool", "list_at_risk_deals", "think"),

    # ---- chat (general; no tool, no skill) ----
    ("こんにちは", "chat", "", "fast"),
    ("ありがとう、助かったよ", "chat", "", "fast"),
    ("君は何ができるの？", "chat", "", "fast"),
    ("CRMとは何の略？", "chat", "", "fast"),
    ("SaaSの一般的な意味を教えて", "chat", "", "fast"),
    ("hi there", "chat", "", "fast"),
    ("what can you do?", "chat", "", "fast"),
    ("おはよう、今日もよろしく", "chat", "", "fast"),
    ("リードタイムって一般にどういう意味？", "chat", "", "fast"),
    ("営業の心構えを一言で言うと？", "chat", "", "fast"),
    ("thanks, that helps", "chat", "", "fast"),
    ("少し雑談に付き合って", "chat", "", "fast"),

    # ---- chat but think (open-ended reasoning, still no tool) ----
    ("なぜ初回訪問で決裁者の確認が重要なの？", "chat", "", "think"),
    ("値引きと差別化、どちらを優先すべきか考えを聞かせて", "chat", "", "think"),
    ("why does engagement without progress signal risk?", "chat", "", "think"),
]


def _embed(queries: list[str], model_name: str):
    """Embed with the project's MiniLM. Prefer fastembed (the runtime path); fall
    back to sentence-transformers with the SAME model when the fastembed cache is
    incomplete — the vectors are equivalent for a feasibility read."""
    try:
        from fastembed import TextEmbedding
        m = TextEmbedding(model_name, threads=1)
        return np.array(list(m.embed(queries)), dtype=np.float32), "fastembed", \
            (lambda q: list(m.embed([q])))
    except Exception as e:  # noqa: BLE001 — fall back to sentence-transformers
        print(f"  (fastembed unavailable: {str(e)[:50]}... -> sentence-transformers)")
        from sentence_transformers import SentenceTransformer
        st = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        return np.asarray(st.encode(queries, normalize_embeddings=True), dtype=np.float32), \
            "sentence-transformers", (lambda q: st.encode([q], normalize_embeddings=True))


def main() -> None:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.metrics import accuracy_score, f1_score
    from senpai import config

    queries = [d[0] for d in DATA]
    y_dest = np.array([d[1] for d in DATA])
    y_tool = np.array([d[2] for d in DATA])
    y_mode = np.array([d[3] for d in DATA])

    print(f"dataset: {len(DATA)} queries")
    print(f"  destination: {dict(Counter(y_dest))}")
    print(f"  mode       : {dict(Counter(y_mode))}")
    print(f"  embedding model: {config.EMBED_MODEL}")
    print("embedding queries (CPU, MiniLM)…")

    import time
    t0 = time.perf_counter()
    X, backend, embed_one = _embed(queries, config.EMBED_MODEL)
    embed_ms = (time.perf_counter() - t0) * 1000
    # warm single-query latency (what the live path actually pays)
    t1 = time.perf_counter()
    _ = embed_one(queries[0])
    warm_ms = (time.perf_counter() - t1) * 1000
    print(f"  backend={backend}; embedded {len(queries)} in {embed_ms:.0f} ms; "
          f"warm single-query ~{warm_ms:.1f} ms\n")

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    clf = lambda: LogisticRegression(max_iter=2000, C=4.0)

    def cv(X_, y_, name):
        pred = cross_val_predict(clf(), X_, y_, cv=skf)
        acc = accuracy_score(y_, pred)
        f1 = f1_score(y_, pred, average="macro")
        print(f"[{name}] 5-fold CV accuracy={acc:.3f}  macro-F1={f1:.3f}")
        return pred, acc

    print("=== HEAD A — destination (research|tool|chat) ===")
    dest_pred, dest_acc = cv(X, y_dest, "destination")
    # majority + rule baselines
    maj = Counter(y_dest).most_common(1)[0][1] / len(y_dest)
    print(f"  baseline (majority class)         = {maj:.3f}")

    # rule baseline: current _is_research_intent, scored on the research-vs-rest split
    from senpai.api.server import _is_research_intent
    rule_research = np.array(["research" if _is_research_intent(q) else "other" for q in queries])
    true_research = np.array(["research" if d == "research" else "other" for d in y_dest])
    rule_acc = accuracy_score(true_research, rule_research)
    clf_research = np.array(["research" if d == "research" else "other" for d in dest_pred])
    clf_research_acc = accuracy_score(true_research, clf_research)
    print(f"  research-detection: rule(_is_research_intent)={rule_acc:.3f}  vs  classifier={clf_research_acc:.3f}")

    print("\n=== HEAD A' — tool_hint (only tool-labeled queries) ===")
    tmask = y_dest == "tool"
    Xt, yt = X[tmask], y_tool[tmask]
    # small per-class counts → 3-fold so every fold has each tool where possible
    nmin = min(Counter(yt).values())
    folds = max(2, min(3, nmin))
    skf_t = StratifiedKFold(n_splits=folds, shuffle=True, random_state=0)
    pred_t = cross_val_predict(clf(), Xt, yt, cv=skf_t)
    print(f"  {tmask.sum()} tool queries across {len(set(yt))} tools; {folds}-fold")
    print(f"[tool_hint] CV accuracy={accuracy_score(yt, pred_t):.3f}")

    print("\n=== HEAD B — mode (fast|think) ===")
    mode_pred, mode_acc = cv(X, y_mode, "mode")
    maj_m = Counter(y_mode).most_common(1)[0][1] / len(y_mode)
    print(f"  baseline (majority class)         = {maj_m:.3f}")
    # rule baseline: DeterministicReasoningRouter on query alone (no tools_used)
    from senpai.llm.routing import DeterministicReasoningRouter, RoutingRequest
    r = DeterministicReasoningRouter()
    rule_mode = np.array(["think" if r.route(RoutingRequest(message=q)).think else "fast"
                          for q in queries])
    rule_mode_acc = accuracy_score(y_mode, rule_mode)
    print(f"  mode: rule(DeterministicRouter, query-only)={rule_mode_acc:.3f}  vs  classifier={mode_acc:.3f}")

    print("\n=== misclassified (destination) ===")
    for q, t, p in zip(queries, y_dest, dest_pred):
        if t != p:
            print(f"  {t:>8} -> {p:<8} | {q}")

    print("\nNOTE: tiny hand-labeled set — this measures FEASIBILITY (separability"
          " in MiniLM space), not production accuracy.")


if __name__ == "__main__":
    main()
