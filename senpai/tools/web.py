"""web_search tool — the one external tool, shared by both chats.

Ported from demo/tools.py: real web search via Tavily when TAVILY_API_KEY is set
in a repo-root .env, otherwise a realistic canned fallback so the chat never
breaks offline. Stdlib only (urllib) — no extra dependency.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

_HTTP_TIMEOUT = 6  # seconds; short so a hang can't stall the chat


def _load_dotenv() -> None:
    """Load repo-root .env keys into os.environ (stdlib only; never overrides a
    value already set in the environment)."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")


def _post_json(url: str, payload: dict, timeout: int = _HTTP_TIMEOUT) -> dict | None:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": "senpai/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# Canned fallbacks so a missing key / network hiccup never breaks the chat.
_SEARCH_CANNED = {
    "製造": [
        "中小製造業のIT投資は基幹システム刷新とセキュリティ対策が中心(業界レポート)。",
        "人手不足を背景に生産管理・在庫管理のクラウド化が進行。",
        "サイバー保険とEDR導入の需要が増加傾向。",
    ],
    "医療": [
        "医療機関は電子カルテ更新とランサムウェア対策への投資を優先。",
        "オンライン診療の普及でネットワーク増強ニーズが拡大。",
    ],
}


def web_search_typed(query: str, max_results: int = 4) -> dict:
    """Structured web search for deterministic research orchestration.

    Unlike the legacy chat tool below, this does not use canned fallback text:
    research needs explicit provenance or an explicit unavailable state.
    """
    if not TAVILY_API_KEY:
        return {"status": "error", "query": query, "answer": "", "results": [],
                "live": False, "reason": "missing_api_key"}
    data = _post_json(
        "https://api.tavily.com/search",
        {"api_key": TAVILY_API_KEY, "query": query,
         "max_results": max_results, "search_depth": "basic", "include_answer": True},
        timeout=12,
    )
    if data is None:
        return {"status": "error", "query": query, "answer": "", "results": [],
                "live": False, "reason": "request_failed"}
    results = []
    for r in (data.get("results") or [])[:max_results]:
        results.append({
            "title": (r.get("title") or "").strip(),
            "url": r.get("url", ""),
            "content": (r.get("content") or "").strip().replace("\n", " "),
            "score": r.get("score"),
        })
    return {
        "status": "found" if results else "not_found",
        "query": query,
        "answer": (data.get("answer") or "").strip(),
        "results": results,
        "live": True,
        "reason": "" if results else "no_results",
    }


def web_search(query: str) -> str:
    """Search the web for a query. Uses Tavily when configured; falls back to
    canned results on missing key / network failure so the demo never breaks."""
    if TAVILY_API_KEY:
        data = _post_json(
            "https://api.tavily.com/search",
            {"api_key": TAVILY_API_KEY, "query": query,
             "max_results": 4, "search_depth": "basic", "include_answer": True},
            timeout=12,
        )
        if data and data.get("results"):
            lines = []
            for r in data["results"][:4]:
                title = (r.get("title") or "").strip()
                snippet = (r.get("content") or "").strip().replace("\n", " ")
                if len(snippet) > 160:
                    snippet = snippet[:157] + "…"
                url = r.get("url", "")
                lines.append(f"{title} — {snippet} ({url})")
            answer = (data.get("answer") or "").strip()
            head = f"{answer}\n\n" if answer else ""
            return head + "検索結果:\n- " + "\n- ".join(lines)
    # fallback: canned results
    q = query.lower()
    for key, results in _SEARCH_CANNED.items():
        if key in query or key in q:
            return "検索結果(参考):\n- " + "\n- ".join(results)
    return ("検索結果(参考):\n- 概要: 一般的な業界動向の記事。\n"
            "- 公式サイト: 一次情報源。\n- ニュース: 最近の関連報道。")
