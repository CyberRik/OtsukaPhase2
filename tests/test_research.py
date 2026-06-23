from __future__ import annotations

import json

from senpai.api import server
from senpai.api.server import ChatRequest


def _events(message: str):
    frames = list(server.research_stream(ChatRequest(message=message, role="research")))
    out = []
    for frame in frames:
        line = frame.strip().removeprefix("data:").strip()
        out.append(json.loads(line))
    return out


def _patch_summary(monkeypatch, text: str = "grounded summary"):
    def fake_stream_complete(messages, **kwargs):
        assert kwargs.get("allow_fallback") is False
        assert "Evidence bundle" in messages[0]["content"]
        yield text

    monkeypatch.setattr("senpai.llm.client.stream_complete", fake_stream_complete)


def test_research_microsoft_internal_miss_triggers_web(monkeypatch):
    calls = []

    def fake_web(query: str, max_results: int = 4):
        calls.append(query)
        return {
            "status": "found",
            "query": query,
            "answer": "Microsoft overview",
            "results": [{"title": "Microsoft", "url": "https://www.microsoft.com", "content": "Official"}],
            "live": True,
            "reason": "",
        }

    monkeypatch.setattr(server, "web_search_typed", fake_web)
    _patch_summary(monkeypatch)

    events = _events("Tell me about Microsoft")
    assert any(e["type"] == "resolve" and e["status"] == "not_found" for e in events)
    assert calls and "Microsoft" in calls[0]
    assert any(e["type"] == "web" and e["status"] == "found" for e in events)
    assert any(e["type"] == "answer" and "grounded summary" in e["text"] for e in events)


def test_research_aozora_uses_internal_record_without_web(monkeypatch):
    def fail_web(*_args, **_kwargs):
        raise AssertionError("web_search should not run for resolved internal customer")

    monkeypatch.setattr(server, "web_search_typed", fail_web)
    _patch_summary(monkeypatch)

    events = _events("Tell me about Aozora Services")
    assert any(e["type"] == "resolve" and e["status"] == "resolved" for e in events)
    assert any(e["type"] == "source" and e["key"] == "internal_records" and e["status"] == "found" for e in events)
    assert any(e["type"] == "source" and e["key"] == "web_search" and e["status"] == "skipped" for e in events)


def test_research_yamato_trading_returns_ambiguity(monkeypatch):
    def fail_web(*_args, **_kwargs):
        raise AssertionError("web_search should not run for ambiguous customer")

    monkeypatch.setattr(server, "web_search_typed", fail_web)
    events = _events("Tell me about Yamato Trading")
    resolve = next(e for e in events if e["type"] == "resolve")
    assert resolve["status"] == "ambiguous"
    assert len(resolve["candidates"]) >= 2
    assert any(e["type"] == "source" and e["key"] == "web_search" and e["status"] == "skipped" for e in events)
    assert any(e["type"] == "answer" and "複数" in e["text"] for e in events)


def test_research_web_failure_after_internal_miss_is_unavailable(monkeypatch):
    monkeypatch.setattr(server, "web_search_typed", lambda *_args, **_kwargs: {
        "status": "error",
        "query": "Microsoft",
        "answer": "",
        "results": [],
        "live": False,
        "reason": "request_failed",
    })

    events = _events("Tell me about Microsoft")
    assert any(e["type"] == "resolve" and e["status"] == "not_found" for e in events)
    assert any(e["type"] == "web" and e["status"] == "error" for e in events)
    assert any(e["type"] == "unavailable" and e["reason"] == "no_internal_record_and_web_unavailable" for e in events)


def test_research_summarization_never_uses_fallback(monkeypatch):
    monkeypatch.setattr(server, "web_search_typed", lambda *_args, **_kwargs: {
        "status": "found",
        "query": "Microsoft",
        "answer": "",
        "results": [{"title": "Microsoft", "url": "https://www.microsoft.com", "content": "Official"}],
        "live": True,
        "reason": "",
    })

    def fake_stream_complete(_messages, **kwargs):
        assert kwargs.get("allow_fallback") is False
        raise RuntimeError("primary down")

    monkeypatch.setattr("senpai.llm.client.stream_complete", fake_stream_complete)
    events = _events("Tell me about Microsoft")
    assert any(e["type"] == "unavailable" and e["reason"] == "llm_unreachable" for e in events)
