"""site_intel — headless-browser website-intel agent (crawl a company site → brief).

Senpai's `web_search` (see `web.py`) returns snippets; it cannot *walk a site*. This
tool takes a company URL, crawls it (a real headless browser when available, plain
`requests` otherwise), extracts structured intel (products, news, IR/財務 PDFs,
leadership), and produces a grounded pre-call brief with a source URL behind claims.

Three-level graceful degrade, same philosophy as `SENPAI_USE_LLM`:
  1. Playwright + Chromium  → renders JS, streams page screenshots.
  2. requests + lxml        → static fetch, no screenshot (Chromium missing / OOM).
  3. deterministic brief    → heuristic extraction when the LLM is off/unreachable.

Discipline mirrors `web.py` / `gcal.py` / `documents/`: stdlib-first, every heavy dep
lazily imported so a missing library can never break tool import, and the public
`site_intel(...)` entry **never raises** — the ReAct loop can't crash on it.

SAFETY (this fetches arbitrary user-supplied URLs):
  * scheme allow-list (http/https only),
  * SSRF guard — resolve the host and reject loopback/private/link-local/reserved IPs,
  * same-registrable-domain restriction, robots.txt (best-effort),
  * per-page timeout, total time budget, per-page byte cap, polite inter-request delay.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import socket
import time
from collections import deque, OrderedDict
from functools import lru_cache
from html import unescape
from typing import Any, Callable
from urllib import robotparser
from urllib.parse import urljoin, urlparse, urlsplit

# Live per-page callback (dict event). Mirrors senpai/research/gather.py's Emit.
Emit = Callable[[dict], None]
_NOOP: Emit = lambda _ev: None

# --- Bounds / politeness knobs ----------------------------------------------
_DEFAULT_MAX_PAGES = 6
_DEFAULT_MAX_DEPTH = 2
_DEFAULT_BUDGET_S = 48.0        # hard ceiling on a whole crawl (slow-scroll needs room)
_PAGE_TIMEOUT_S = 8.0
_MAX_BYTES = 2_000_000          # skip absurdly large responses
_POLITE_DELAY_S = 0.4
_UA = "senpai-siteintel/1.0 (+sales-copilot; respects robots.txt)"

# Live browse feel: after a page loads, scroll it top→bottom capturing a frame at
# each step so the client sees a real, moving browse instead of one static shot.
# More steps + a longer pause = a slower, smoother human-like scroll.
_SCROLL_STEPS = 7               # frames captured while scrolling down a tall page
_SCROLL_SETTLE_MS = 500         # pause per step (paces the scroll + lets images paint)
_FIRST_PAINT_MS = 500           # settle after load before the first frame


def _use_llm() -> bool:
    """Read the shared SENPAI_USE_LLM switch (mirrors senpai/documents/author.py)."""
    return os.environ.get("SENPAI_USE_LLM", "0").lower() not in ("0", "false", "", "no")

# Link classification — Japanese + English keyword hints on the URL/anchor text.
_KIND_HINTS: dict[str, tuple[str, ...]] = {
    "ir": ("ir", "investor", "財務", "決算", "株主", "有価証券", "ir/", "finance"),
    "news": ("news", "press", "release", "topics", "お知らせ", "ニュース", "プレス", "新着"),
    "products": ("product", "service", "solution", "製品", "サービス", "ソリューション", "事業"),
    "company": ("company", "about", "corporate", "profile", "会社", "企業情報", "会社概要", "沿革"),
    "leadership": ("management", "officer", "board", "役員", "経営", "代表", "取締役"),
    "contact": ("contact", "inquiry", "お問い合わせ", "問い合わせ"),
}


# ============================================================================
# Safety: URL / SSRF guards
# ============================================================================
def _is_public_ip(host: str) -> bool:
    """True only if EVERY resolved address for host is a normal public IP. Blocks
    loopback/private/link-local/reserved/multicast — the core SSRF defence."""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def is_safe_url(url: str) -> bool:
    """Gate every fetch: http/https only, has a host, host resolves to public IPs."""
    try:
        p = urlsplit(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    return _is_public_ip(p.hostname)


def _registrable(host: str) -> str:
    """Cheap registrable-domain: last two labels (example.co.jp → co.jp is imperfect
    but we only use it to keep the crawl on the *same* site, and we also compare the
    full host, so over-broad matching is bounded by the seed host anyway)."""
    host = (host or "").lower().split(":")[0]
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _same_site(url: str, root_host: str) -> bool:
    """Same host, or a subdomain of the seed's registrable domain."""
    h = (urlsplit(url).hostname or "").lower()
    if not h:
        return False
    return h == root_host.lower() or h.endswith("." + _registrable(root_host))


# ============================================================================
# Extraction (pure-Python; lxml is already a dependency)
# ============================================================================
def _classify(url: str, anchor: str) -> str | None:
    blob = f"{url} {anchor}".lower()
    for kind, hints in _KIND_HINTS.items():
        if any(h in blob for h in hints):
            return kind
    return None


def _text_from_html(html: str, url: str) -> str:
    """Main-content text. trafilatura when present (best), else an lxml heuristic."""
    try:  # best: readability-grade extraction
        import trafilatura  # type: ignore
        txt = trafilatura.extract(html, url=url, favor_recall=True)
        if txt:
            return txt.strip()
    except Exception:
        pass
    try:
        import lxml.html as LH  # type: ignore
        doc = LH.fromstring(html)
        for bad in doc.xpath("//script | //style | //noscript | //nav | //footer"):
            bad.getparent().remove(bad) if bad.getparent() is not None else None
        chunks = [t.strip() for t in doc.xpath(
            "//h1//text() | //h2//text() | //h3//text() | //p//text() | //li//text()")]
        return "\n".join(c for c in chunks if c)[:20000]
    except Exception:
        return ""


def _extract(html: str, base_url: str) -> dict[str, Any]:
    """Parse one page → title, main text, and classified in/out links + assets."""
    title = ""
    links: list[dict[str, str]] = []
    pdfs: list[dict[str, str]] = []
    try:
        import lxml.html as LH  # type: ignore
        doc = LH.fromstring(html)
        t = doc.xpath("//title/text()")
        title = unescape((t[0] if t else "").strip())
        for a in doc.xpath("//a[@href]"):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            absu = urljoin(base_url, href)
            if urlsplit(absu).scheme not in ("http", "https"):
                continue
            anchor = " ".join(a.itertext()).strip()[:120]
            if absu.lower().split("?")[0].endswith(".pdf"):
                pdfs.append({"url": absu, "text": anchor})
            else:
                links.append({"url": absu.split("#")[0], "text": anchor,
                              "kind": _classify(absu, anchor) or ""})
    except Exception:
        pass
    return {"title": title, "text": _text_from_html(html, base_url),
            "links": links, "pdfs": pdfs}


# ============================================================================
# Fetch backends
# ============================================================================
def _fetch_static(url: str) -> dict[str, Any] | None:
    """requests-based fetch with size cap. None on any failure (never raises)."""
    try:
        import requests  # type: ignore
        with requests.get(url, headers={"User-Agent": _UA}, timeout=_PAGE_TIMEOUT_S,
                          stream=True, allow_redirects=True) as r:
            # Re-check the *final* URL after redirects — a redirect can smuggle in
            # a private target (SSRF via 302).
            if not is_safe_url(r.url):
                return None
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype and "xml" not in ctype and ctype:
                return {"status": r.status_code, "html": "", "final_url": r.url}
            body = b""
            for chunk in r.iter_content(8192):
                body += chunk
                if len(body) > _MAX_BYTES:
                    break
            enc = r.encoding or "utf-8"
            return {"status": r.status_code,
                    "html": body.decode(enc, errors="replace"), "final_url": r.url}
    except Exception:
        return None


class _BrowserSession:
    """Lazy Playwright/Chromium session. Any failure (import, launch, OOM) leaves
    `.ok` False so the caller silently drops to the static backend."""

    def __init__(self) -> None:
        self.ok = False
        self._pw = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "_BrowserSession":
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            ctx = self._browser.new_context(
                user_agent=_UA, viewport={"width": 1280, "height": 800})
            self._page = ctx.new_page()
            self.ok = True
        except Exception:
            self.close()
        return self

    def fetch(self, url: str,
              on_frame: Callable[[str], None] | None = None) -> dict[str, Any] | None:
        """Render a page; stream scroll frames via `on_frame`, return html + final JPEG.

        When `on_frame` is given the page is scrolled top→bottom and a base64 JPEG is
        handed back at each step — that is what turns the client view into a live,
        moving browse instead of a single frozen screenshot."""
        try:
            resp = self._page.goto(url, timeout=int(_PAGE_TIMEOUT_S * 1000),
                                   wait_until="domcontentloaded")
            if not is_safe_url(self._page.url):  # post-redirect SSRF re-check
                return None
            self._settle(_FIRST_PAINT_MS)       # let above-the-fold content paint
            if on_frame is not None:
                self._stream_scroll(on_frame)
            html = self._page.content()
            shot = self._shoot()
            return {"status": resp.status if resp else 200, "html": html,
                    "final_url": self._page.url,
                    "screenshot_b64": base64.b64encode(shot).decode("ascii") if shot else ""}
        except Exception:
            return None

    def _settle(self, ms: int) -> None:
        try:
            self._page.wait_for_timeout(ms)
        except Exception:
            pass

    def _shoot(self) -> bytes | None:
        try:
            return self._page.screenshot(type="jpeg", quality=52, full_page=False)
        except Exception:
            return None

    def _stream_scroll(self, on_frame: Callable[[str], None]) -> None:
        """Walk the viewport top→bottom, emitting a JPEG frame per step. Short pages
        (single viewport) emit just the top frame — the whole page is already shown."""
        def frame() -> None:
            shot = self._shoot()
            if shot:
                try:
                    on_frame(base64.b64encode(shot).decode("ascii"))
                except Exception:
                    pass
        frame()  # top of page
        try:
            height = int(self._page.evaluate("() => document.body.scrollHeight") or 0)
        except Exception:
            height = 0
        vh = 800
        if height <= vh + 80:
            return  # fits one screen — nothing more to reveal
        steps = min(_SCROLL_STEPS, max(1, (height - vh) // vh + 1))
        for i in range(1, steps + 1):
            y = int((height - vh) * i / steps)
            try:
                self._page.evaluate("(y) => window.scrollTo(0, y)", y)
            except Exception:
                pass
            self._settle(_SCROLL_SETTLE_MS)
            frame()
        try:                                    # rewind for the archived screenshot
            self._page.evaluate("() => window.scrollTo(0, 0)")
        except Exception:
            pass
        self._settle(120)

    def close(self) -> None:
        for obj, meth in ((self._browser, "close"), (self._pw, "stop")):
            try:
                getattr(obj, meth)() if obj else None
            except Exception:
                pass

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ============================================================================
# Crawl
# ============================================================================
def crawl_site(url: str, *, max_pages: int = _DEFAULT_MAX_PAGES,
               max_depth: int = _DEFAULT_MAX_DEPTH, budget_s: float = _DEFAULT_BUDGET_S,
               use_browser: bool = True, emit: Emit | None = None) -> dict[str, Any]:
    """BFS-crawl a site within bounds; emit a `crawl_page` event per page. Returns a
    structured SiteIntel dict. Never raises — errors surface in the return payload."""
    emit = emit or _NOOP
    if not is_safe_url(url):
        emit({"type": "crawl_error", "reason": "unsafe_or_unreachable_url", "url": url})
        return {"start_url": url, "ok": False, "reason": "unsafe_or_unreachable_url",
                "pages": [], "products": [], "news": [], "pdfs": [], "backend": "none"}

    root_host = urlsplit(url).hostname or ""
    rp = _load_robots(url)
    started = time.monotonic()
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(url, 0)])
    pages: list[dict[str, Any]] = []
    products: list[dict[str, str]] = []
    news: list[dict[str, str]] = []
    pdfs: list[dict[str, str]] = []

    with (_BrowserSession() if use_browser else _nullctx()) as sess:
        browser_ok = bool(getattr(sess, "ok", False))
        backend = "playwright" if browser_ok else "requests"
        while queue and len(pages) < max_pages:
            if time.monotonic() - started > budget_s:
                break
            cur, depth = queue.popleft()
            norm = cur.rstrip("/")
            if norm in seen or not _same_site(cur, root_host):
                continue
            seen.add(norm)
            if rp is not None and not _robots_can_fetch(rp, cur):
                continue

            def _on_frame(b64: str, _url: str = cur, _n: int = len(pages) + 1) -> None:
                # Stream live scroll frames for the browser-sim. `crawl_frame` is a
                # visual-only event; metadata still rides the final `crawl_page`.
                emit({"type": "crawl_frame", "url": _url, "index": _n,
                      "screenshot_b64": b64})

            res = (sess.fetch(cur, on_frame=_on_frame) if browser_ok else None) \
                or _fetch_static(cur)
            if res is None:
                emit({"type": "crawl_page", "url": cur, "status": 0, "title": "",
                      "depth": depth, "ok": False})
                continue

            ext = _extract(res.get("html", ""), res.get("final_url", cur))
            page = {"url": res.get("final_url", cur), "status": res.get("status", 0),
                    "title": ext["title"], "depth": depth,
                    "snippet": ext["text"][:280], "text": ext["text"], "ok": True}
            if "screenshot_b64" in res:
                page["screenshot_b64"] = res["screenshot_b64"]
            pages.append(page)

            for pdf in ext["pdfs"]:
                if pdf not in pdfs:
                    pdfs.append(pdf)
            for lk in ext["links"]:
                if lk["kind"] == "products" and lk not in products:
                    products.append(lk)
                elif lk["kind"] == "news" and lk not in news:
                    news.append(lk)
                if (depth + 1 <= max_depth and lk["url"].rstrip("/") not in seen
                        and _same_site(lk["url"], root_host)):
                    queue.append((lk["url"], depth + 1))

            emit({"type": "crawl_page", "url": page["url"], "status": page["status"],
                  "title": page["title"], "depth": depth, "index": len(pages),
                  "snippet": page["snippet"], "ok": True,
                  "screenshot_b64": page.get("screenshot_b64", ""),
                  "found": {"products": len(products), "news": len(news),
                            "pdfs": len(pdfs)}})
            time.sleep(_POLITE_DELAY_S)

    return {"start_url": url, "ok": bool(pages), "backend": backend,
            "root_host": root_host, "pages": pages, "products": products,
            "news": news, "pdfs": pdfs,
            "reason": "" if pages else "no_pages_fetched"}


class _nullctx:
    """Stand-in for `_BrowserSession` when use_browser=False (no `.ok`)."""
    ok = False

    def __enter__(self) -> "_nullctx":
        return self

    def __exit__(self, *exc: Any) -> None:
        pass


def _load_robots(url: str) -> robotparser.RobotFileParser | None:
    try:
        p = urlsplit(url)
        rp = robotparser.RobotFileParser()
        rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
        rp.read()
        return rp
    except Exception:
        return None  # best-effort: no robots ⇒ allow (bounded crawl anyway)


def _robots_can_fetch(rp: robotparser.RobotFileParser, url: str) -> bool:
    try:
        return rp.can_fetch(_UA, url)
    except Exception:
        return True


# ============================================================================
# Brief synthesis
# ============================================================================
def build_brief(intel: dict[str, Any], *, use_llm: bool = True,
                emit: Emit | None = None) -> dict[str, Any]:
    """Turn a crawl result into a grounded intel brief. LLM-structured when available,
    deterministic heuristic otherwise. Always returns a dict; never raises."""
    emit = emit or _NOOP
    if not intel.get("pages"):
        return {"markdown": "", "ok": False, "reason": intel.get("reason", "no_pages"),
                "sources": []}
    sources = [{"url": p["url"], "title": p["title"]} for p in intel["pages"]]
    if use_llm:
        emit({"type": "crawl_status", "phase": "synthesizing"})
        try:
            md = _llm_brief(intel)
            if md:
                return {"markdown": md, "ok": True, "reason": "llm", "sources": sources}
        except Exception:
            pass  # fall through to deterministic
    return {"markdown": _deterministic_brief(intel), "ok": True,
            "reason": "deterministic", "sources": sources}


def _evidence_bundle(intel: dict[str, Any]) -> str:
    lines = [f"# Crawled site: {intel['start_url']} ({intel['root_host']})",
             f"Pages visited: {len(intel['pages'])}"]
    for p in intel["pages"]:
        lines.append(f"\n## {p['title'] or '(untitled)'} — {p['url']}")
        lines.append(p["text"][:1500])
    if intel["products"]:
        lines.append("\n## Product/service pages:\n" + "\n".join(
            f"- {x['text'] or x['url']} ({x['url']})" for x in intel["products"][:12]))
    if intel["news"]:
        lines.append("\n## News/press:\n" + "\n".join(
            f"- {x['text'] or x['url']} ({x['url']})" for x in intel["news"][:12]))
    if intel["pdfs"]:
        lines.append("\n## IR / documents (PDF):\n" + "\n".join(
            f"- {x['text'] or x['url']} ({x['url']})" for x in intel["pdfs"][:12]))
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _otsuka_catalog() -> str:
    """Compact, category-level summary of what Otsuka actually sells, injected into
    the brief prompt so the sales-angle section proposes a concrete wedge grounded in
    our real catalog instead of generic platitudes. Category-level (not per-SKU) keeps
    the prompt tight. Never raises — a missing/broken file yields an empty string."""
    try:
        from senpai import config
        rows = json.loads((config.SEED_DIR / "products.json").read_text(encoding="utf-8"))
    except Exception:
        return ""
    cats: "OrderedDict[str, list[str]]" = OrderedDict()
    for r in rows if isinstance(rows, list) else []:
        maj = str(r.get("major") or "").strip()
        mid = str(r.get("mid") or "").strip()
        if not maj:
            continue
        cats.setdefault(maj, [])
        if mid and mid not in cats[maj]:
            cats[maj].append(mid)
    return "\n".join(f"- {maj}: {'、'.join(mids)}" for maj, mids in cats.items())


def _llm_brief(intel: dict[str, Any]) -> str:
    from senpai.llm.client import simple_complete
    catalog = _otsuka_catalog()
    catalog_block = (
        "\n\n【当社（Otsuka）取扱商材カテゴリ（切り口検討の参考）】\n"
        "以下は当社の商材知識であり、対象企業に関する事実ではないため出典は不要。"
        "切り口は、対象企業の状況（証拠）と当社商材の接点として具体的に述べること。\n"
        + catalog
    ) if catalog else ""
    prompt = (
        "あなたはOtsukaの法人営業を支援するリサーチアシスタントです。Otsukaは、OA機器・"
        "PC/周辺機器・サーバー・ストレージ・ネットワーク機器・ソフトウェア/RPA・導入/保守"
        "役務を扱う、法人向けITインフラの販売・構築会社です。\n"
        "以下は対象企業の公式サイトをクロールして得た証拠です。対象企業に関する事実の主張は、"
        "証拠に書かれている内容のみを使い、各主張の末尾に出典URLを付けてください。推測や一般論で"
        "埋めないこと（当社商材との接点の提案は、証拠にある相手の状況を根拠にすること）。\n\n"
        "訪問前ブリーフを日本語で、次の構成で作成してください:\n"
        "0. 一言サマリー（3行以内）: なぜ今アプローチすべきか＋最も刺さる切り口\n"
        "1. 商談の切り口・キーパーソン: 対象の状況（証拠）と当社商材の具体的な接点。"
        "会うべき人物・部署が証拠にあれば明記\n"
        "2. 会社概要（事業・規模）\n"
        "3. 主要な製品・サービス\n"
        "4. 最近のニュース・動き\n"
        "5. IR/財務資料（あれば）"
        f"{catalog_block}\n\n"
        f"【証拠】\n{_evidence_bundle(intel)}")
    return simple_complete(
        [{"role": "user", "content": prompt}], temperature=0.3, no_think=True,
        allow_fallback=False, label="site_intel").strip()


def _deterministic_brief(intel: dict[str, Any]) -> str:
    """Offline heuristic brief — no LLM. Grounded entirely in extracted structure."""
    out = [f"# サイトインテル: {intel['root_host']}",
           f"起点: {intel['start_url']} ／ 取得ページ数: {len(intel['pages'])}"
           f"（バックエンド: {intel['backend']}）\n"]
    home = intel["pages"][0]
    if home.get("snippet"):
        out.append("## 会社概要（サイト冒頭より）\n" + home["snippet"] + f"\n（出典: {home['url']}）\n")
    if intel["products"]:
        out.append("## 製品・サービス\n" + "\n".join(
            f"- {x['text'] or x['url']}（{x['url']}）" for x in intel["products"][:10]) + "\n")
    if intel["news"]:
        out.append("## 最近のニュース・プレス\n" + "\n".join(
            f"- {x['text'] or x['url']}（{x['url']}）" for x in intel["news"][:10]) + "\n")
    if intel["pdfs"]:
        out.append("## IR・財務資料（PDF）\n" + "\n".join(
            f"- {x['text'] or x['url']}（{x['url']}）" for x in intel["pdfs"][:10]) + "\n")
    out.append("## 訪問前メモ\n上記はサイトから抽出した一次情報です。商談前に製品ラインと"
               "直近のニュースを確認し、相手の事業に紐づく切り口を用意してください。")
    return "\n".join(out)


# ============================================================================
# Tool entry (chat ReAct loop) — returns a string, never raises
# ============================================================================
def site_intel(url: str = "", max_pages: int = _DEFAULT_MAX_PAGES,
               max_depth: int = _DEFAULT_MAX_DEPTH) -> str:
    """Crawl a company website and return a grounded pre-call intel brief (text).

    Safe to call from the ReAct loop: bounded, SSRF-guarded, and never raises. Each
    visited page is recorded to `crawl_trace` so the chat loop can surface the browse
    as `crawl_page` events. `SENPAI_USE_LLM=0` still yields a deterministic brief."""
    from senpai.tools import crawl_trace

    url = (url or "").strip()
    if not url:
        return "[error] site_intel needs a url (e.g. https://www.example.co.jp)."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not is_safe_url(url):
        return (f"このURLはクロールできません（到達不可、または内部/非公開アドレス）: {url}")

    try:
        intel = crawl_site(url, max_pages=max(1, min(int(max_pages), 12)),
                           max_depth=max(1, min(int(max_depth), 3)),
                           emit=lambda ev: crawl_trace.record(ev)
                           if ev.get("type") in ("crawl_page", "crawl_frame") else None)
    except Exception as e:  # noqa: BLE001 — the loop must never crash
        return f"[error] site_intel failed while crawling {url}: {e}"

    if not intel.get("ok"):
        return f"{url} からページを取得できませんでした（{intel.get('reason', 'unknown')}）。"
    brief = build_brief(intel, use_llm=_use_llm())
    return brief.get("markdown") or _deterministic_brief(intel)


# ============================================================================
# Open-web research: search → pick sites → crawl each → synthesize (shares engine)
# ============================================================================
def research_web(query: str, *, max_sites: int = 3, max_pages_per_site: int = 3,
                 emit: Emit | None = None) -> dict[str, Any]:
    """Answer a question that has no given URL: web-search for it, crawl the top
    distinct-domain result sites, and gather evidence. Returns a structured result
    (query, sites, crawls, search_answer). Never raises. The search step needs
    TAVILY_API_KEY (see web.py); the crawl/synthesis steps work regardless."""
    emit = emit or _NOOP
    from senpai.tools.web import web_search_typed

    search = web_search_typed(query, max_results=8)
    picked: list[str] = []
    seen_dom: set[str] = set()
    for r in search.get("results", []):
        u = (r.get("url") or "").strip()
        if not u or not is_safe_url(u):
            continue
        dom = _registrable(urlsplit(u).hostname or "")
        if dom in seen_dom:
            continue
        seen_dom.add(dom)
        picked.append(u)
        if len(picked) >= max_sites:
            break

    emit({"type": "research_plan", "query": query, "sites": picked,
          "search_answer": search.get("answer", ""),
          "search_ok": search.get("status") == "found"})

    crawls: list[dict[str, Any]] = []
    for u in picked:
        intel = crawl_site(u, max_pages=max_pages_per_site, max_depth=1, emit=emit)
        if intel.get("ok"):
            crawls.append(intel)

    return {"query": query, "ok": bool(crawls) or bool(search.get("answer")),
            "sites": picked, "crawls": crawls,
            "search_answer": search.get("answer", ""),
            "search_status": search.get("status", ""),
            "search_results": search.get("results", [])}


def _research_answer(bundle: dict[str, Any], *, use_llm: bool) -> str:
    """Cited answer for a research bundle — LLM when available, else deterministic."""
    crawls, query = bundle["crawls"], bundle["query"]
    if use_llm and (crawls or bundle["search_answer"]):
        try:
            from senpai.llm.client import simple_complete
            evidence = [f"検索まとめ: {bundle['search_answer']}"] if bundle["search_answer"] else []
            for intel in crawls:
                evidence.append(_evidence_bundle(intel))
            prompt = (
                "あなたはOtsukaの営業担当者を支援するリサーチアシスタントです。以下の証拠"
                "（Web検索結果と、実際に巡回した各サイトの内容）だけを使って、質問に日本語で"
                "答えてください。推測で埋めず、各主張の末尾に出典URLを付けること。\n\n"
                f"【質問】{query}\n\n【証拠】\n" + "\n\n".join(evidence)[:12000])
            out = simple_complete([{"role": "user", "content": prompt}],
                                  temperature=0.3, no_think=True, allow_fallback=False,
                                  label="web_research").strip()
            if out:
                return out
        except Exception:
            pass
    # deterministic: search summary + what each crawled site yielded
    lines = [f"# 調査: {query}"]
    if bundle["search_answer"]:
        lines.append("## 検索の要約\n" + bundle["search_answer"])
    if not crawls:
        lines.append("\n（巡回できるサイトが見つかりませんでした。"
                     "Web検索にはTAVILY_API_KEYが必要です。）")
    for intel in crawls:
        home = intel["pages"][0]
        lines.append(f"\n## {home['title'] or intel['root_host']} — {home['url']}")
        if home.get("snippet"):
            lines.append(home["snippet"])
        if intel["products"]:
            lines.append("製品/サービス: " + ", ".join(
                x["text"] or x["url"] for x in intel["products"][:5]))
    return "\n".join(lines)


def _research_query(query: str, *, max_sites: int = 3) -> str:
    """Question branch: search → crawl top sites → cited answer. Never raises."""
    from senpai.tools import crawl_trace
    try:
        bundle = research_web(query, max_sites=max(1, min(int(max_sites), 5)),
                              emit=lambda ev: crawl_trace.record(ev)
                              if ev.get("type") in ("crawl_page", "crawl_frame") else None)
    except Exception as e:  # noqa: BLE001 — the loop must never crash
        return f"[error] web_research failed for {query!r}: {e}"
    if not bundle.get("ok"):
        return (f"「{query}」について有効な情報源を取得できませんでした"
                "（Web検索にはTAVILY_API_KEYが必要です）。")
    return _research_answer(bundle, use_llm=_use_llm())


# --- Unified public tool: auto-routes URL vs. question ----------------------
_BARE_DOMAIN_RE = re.compile(r"^[\w-]+(\.[\w-]+)+(/\S*)?$")


def looks_like_url(text: str) -> bool:
    """True if `text` is a single URL or bare domain (no spaces), not a question."""
    t = (text or "").strip()
    if not t or " " in t or "\n" in t:
        return False
    if t.startswith(("http://", "https://")):
        return True
    return bool(_BARE_DOMAIN_RE.match(t))


def web_research(input: str = "", max_pages: int = _DEFAULT_MAX_PAGES,
                 max_sites: int = 3) -> str:
    """Research the open web by actually visiting pages. Auto-routes:

      * a URL / bare domain  → crawl that site and return a grounded pre-call brief,
      * a question           → web-search it, crawl the top result sites, and answer
                               with citations (needs TAVILY_API_KEY for the search).

    Bounded, SSRF-guarded, and never raises — safe for the ReAct loop. Visited pages
    are recorded to `crawl_trace` so the chat loop can replay the browse."""
    text = (input or "").strip()
    if not text:
        return "[error] web_research needs a URL or a question."
    if looks_like_url(text):
        return site_intel(text, max_pages=max_pages)
    return _research_query(text, max_sites=max_sites)


if __name__ == "__main__":  # tiny smoke: hit a stable public page
    print(site_intel("https://example.com", max_pages=2, max_depth=1)[:800])
