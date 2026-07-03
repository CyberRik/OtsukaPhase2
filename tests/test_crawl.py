"""Hermetic tests for the site_intel crawler (senpai/tools/crawl.py).

No network, no Chromium: the static fetch backend and robots loader are monkeypatched
to serve canned HTML, so this exercises the BFS bounds, extraction, link
classification, SSRF guard, and the deterministic (LLM-off) brief entirely offline.
"""
from __future__ import annotations

import pytest

from senpai.tools import crawl

# --- A tiny fake site --------------------------------------------------------
_SITE = {
    "https://acme.example": """
        <html><head><title>アクメ商事 | 会社概要</title></head><body>
        <h1>アクメ商事</h1><p>中小製造業向けのITソリューションを提供しています。</p>
        <a href="/products">製品・サービス</a>
        <a href="/news">ニュース</a>
        <a href="/ir">IR・決算情報</a>
        <a href="/ir/2026q1.pdf">2026年度 第1四半期 決算説明資料</a>
        <a href="https://other.example/x">外部リンク</a>
        </body></html>""",
    "https://acme.example/products": """
        <html><head><title>製品一覧</title></head><body>
        <h2>製品ラインナップ</h2><p>サーバー、ネットワーク機器、セキュリティ製品。</p>
        </body></html>""",
    "https://acme.example/news": """
        <html><head><title>プレスリリース</title></head><body>
        <h2>新製品を発表</h2><p>新しいクラウドサービスを開始しました。</p>
        </body></html>""",
    "https://acme.example/ir": """
        <html><head><title>IR情報</title></head><body>
        <a href="/ir/annual.pdf">有価証券報告書</a></body></html>""",
}


@pytest.fixture(autouse=True)
def _fast_and_offline(monkeypatch):
    """Serve canned HTML, allow the fake domain, skip robots + politeness delay."""
    def fake_fetch(url: str):
        html = _SITE.get(url.rstrip("/"))
        if html is None:
            return None
        return {"status": 200, "html": html, "final_url": url}

    monkeypatch.setattr(crawl, "_fetch_static", fake_fetch)
    monkeypatch.setattr(crawl, "is_safe_url", lambda u: u.startswith("https://acme.example"))
    monkeypatch.setattr(crawl, "_load_robots", lambda url: None)
    monkeypatch.setattr(crawl, "_POLITE_DELAY_S", 0.0)


# --- SSRF guard (the real one, not the patched shim) -------------------------
@pytest.mark.parametrize("url", [
    "http://localhost:8000", "http://127.0.0.1/", "http://169.254.169.254/",
    "http://10.0.0.5/", "file:///etc/passwd", "ftp://example.com", "notaurl",
])
def test_ssrf_blocks_unsafe(url, monkeypatch):
    monkeypatch.undo()  # use the real is_safe_url for this test
    assert crawl.is_safe_url(url) is False


# --- Extraction --------------------------------------------------------------
def test_extract_pulls_title_links_and_pdfs():
    ext = crawl._extract(_SITE["https://acme.example"], "https://acme.example")
    assert "アクメ商事" in ext["title"]
    kinds = {l["kind"] for l in ext["links"]}
    assert "products" in kinds and "news" in kinds and "ir" in kinds
    assert any(p["url"].endswith(".pdf") for p in ext["pdfs"])


# --- Crawl BFS + bounds ------------------------------------------------------
def test_crawl_walks_site_and_collects_assets():
    events = []
    intel = crawl.crawl_site("https://acme.example", use_browser=False,
                             emit=events.append)
    assert intel["ok"] and intel["backend"] == "requests"
    urls = {p["url"].rstrip("/") for p in intel["pages"]}
    assert "https://acme.example" in urls
    assert "https://acme.example/products" in urls  # depth-1 same-site followed
    # off-site link never fetched
    assert not any("other.example" in u for u in urls)
    assert intel["products"] and intel["news"] and intel["pdfs"]
    assert [e for e in events if e["type"] == "crawl_page"]


def test_crawl_respects_max_pages():
    intel = crawl.crawl_site("https://acme.example", use_browser=False, max_pages=2)
    assert len(intel["pages"]) <= 2


def test_crawl_stays_same_site():
    intel = crawl.crawl_site("https://acme.example", use_browser=False)
    assert all("acme.example" in p["url"] for p in intel["pages"])


# --- Brief (deterministic / LLM-off) -----------------------------------------
def test_deterministic_brief_is_grounded():
    intel = crawl.crawl_site("https://acme.example", use_browser=False)
    brief = crawl.build_brief(intel, use_llm=False)
    assert brief["ok"] and brief["reason"] == "deterministic"
    assert "acme.example" in brief["markdown"]
    assert brief["sources"]  # every page is a citable source


def test_site_intel_entrypoint_never_raises(monkeypatch):
    monkeypatch.setenv("SENPAI_USE_LLM", "0")  # force deterministic path
    out = crawl.site_intel("acme.example")  # scheme auto-prefixed
    assert isinstance(out, str) and "acme.example" in out


# --- Unified web_research router: URL vs. question --------------------------
@pytest.mark.parametrize("text,is_url", [
    ("https://www.acme.co.jp", True),
    ("acme.example", True),
    ("acme.co.jp/products", True),
    ("築地の営業会社トップ5", False),
    ("tell me about acme", False),
    ("what is acme.com known for", False),  # has spaces → a question
])
def test_looks_like_url(text, is_url):
    assert crawl.looks_like_url(text) is is_url


def test_web_research_routes_url_to_crawl(monkeypatch):
    monkeypatch.setenv("SENPAI_USE_LLM", "0")
    out = crawl.web_research("acme.example")  # URL branch → pre-call brief
    assert "acme.example" in out and "製品" in out


def test_web_research_routes_question_to_search(monkeypatch):
    monkeypatch.setenv("SENPAI_USE_LLM", "0")

    def fake_search(query, max_results=8):
        return {"status": "found", "query": query, "answer": "概況。",
                "results": [{"url": "https://acme.example", "title": "アクメ", "content": "x"}],
                "live": True}
    monkeypatch.setattr("senpai.tools.web.web_search_typed", fake_search)
    out = crawl.web_research("築地の営業会社トップ5")  # question branch → search+crawl
    assert "acme.example" in out


def test_crawl_unsafe_url_returns_error_not_raise():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(crawl, "is_safe_url", lambda u: False)
    intel = crawl.crawl_site("https://acme.example", use_browser=False)
    assert intel["ok"] is False and intel["reason"] == "unsafe_or_unreachable_url"
    monkeypatch.undo()


# --- Open-web research: search → crawl → synthesize --------------------------
def test_web_research_searches_then_crawls(monkeypatch):
    """No URL given: a faked search discovers acme.example, then the real crawler
    walks it and the deterministic synthesizer answers with citations."""
    def fake_search(query, max_results=8):
        return {"status": "found", "query": query, "answer": "築地周辺の営業会社の概況。",
                "results": [{"url": "https://acme.example", "title": "アクメ商事",
                             "content": "営業支援"}], "live": True}
    monkeypatch.setattr("senpai.tools.web.web_search_typed", fake_search)
    events = []
    bundle = crawl.research_web("築地の営業会社トップ5", emit=events.append)
    assert bundle["ok"] and bundle["sites"] == ["https://acme.example"]
    assert any(e["type"] == "research_plan" for e in events)
    assert any(e["type"] == "crawl_page" for e in events)
    answer = crawl._research_answer(bundle, use_llm=False)
    assert "acme.example" in answer and "築地" in answer


def test_web_research_entrypoint_degrades_without_search(monkeypatch):
    monkeypatch.setenv("SENPAI_USE_LLM", "0")

    def empty_search(query, max_results=8):
        return {"status": "error", "query": query, "answer": "", "results": [],
                "live": False, "reason": "missing_api_key"}
    monkeypatch.setattr("senpai.tools.web.web_search_typed", empty_search)
    out = crawl.web_research("築地の営業会社トップ5")
    assert isinstance(out, str) and "TAVILY_API_KEY" in out
