from __future__ import annotations

from senpai.tools import impl


def test_dispatch_forces_confirm_true_for_confirmation_gated_tools(monkeypatch):
    seen = {}

    def fake_generate_docx(**kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setitem(impl._DISPATCH, "generate_docx", fake_generate_docx)

    assert impl.dispatch("generate_docx", {"prompt": "x", "confirm": False}) == "ok"
    assert seen["confirm"] is True


def test_dispatch_leaves_non_confirm_tools_unchanged(monkeypatch):
    seen = {}

    def fake_query_spr(**kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setitem(impl._DISPATCH, "query_spr", fake_query_spr)

    assert impl.dispatch("query_spr", {"customer": "C01"}) == "ok"
    assert seen == {"customer": "C01"}
