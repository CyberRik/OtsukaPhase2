"""Build the committed Segment-Intelligence reports (GraphRAG community summaries).

Run `python -m senpai.graph.build_communities` to (re)write config.COMMUNITIES_PATH.
Like build_index.py, the output is a committed build artifact so the *runtime* never
needs a GPU: the deterministic stats are computed in Python (senpai.graph.communities),
then — if a model is reachable — an LLM writes a short Japanese narrative over ONLY
those stats. Every number in the narrative is verified against the stats
(`ungrounded_numbers`); on ANY failure (hallucinated figure, empty output, server
down) we keep the deterministic templated narrative. So this is safe to run offline:
worst case you get the full deterministic artifact with templated prose.

Writes:
    communities.json           list of report dicts (see communities._report)
    communities.manifest.json  {model, today, counts: {segments, llm, template}}
"""
from __future__ import annotations

import json

from senpai import config
from senpai.data import store
from senpai.graph import communities
from senpai.llm.client import simple_complete

_SYS = (
    "あなたは営業マネージャー向けのアナリストです。与えられた統計（JSON）のみを根拠に、"
    "このセグメント（製品カテゴリ×業界）の傾向を日本語2〜3文で簡潔に要約してください。"
    "規則: (1) 統計に無い数値・割合・金額・件数は一切書かない。(2) 個別の案件IDは書かない。"
    "(3) 事実の要約に徹し、推測や新しい助言を加えない。"
)


def _llm_narrative(report: dict) -> tuple[str | None, str]:
    """Return (narrative, status). narrative is None when the LLM output is unusable
    (transport error, empty, or contains a number not backed by the stats)."""
    stats = {k: report[k] for k in (
        "category", "industry", "n_deals", "n_won", "n_lost", "n_open",
        "win_rate", "top_failure_signals", "top_flags", "recommended_principle_ids")}
    messages = [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": "次の統計を要約してください:\n" + json.dumps(stats, ensure_ascii=False)},
    ]
    try:
        text = simple_complete(messages, temperature=0.4, no_think=True).strip()
    except Exception as e:  # noqa: BLE001 — model optional; fall back to template
        return None, f"llm_error: {e}"
    if not text:
        return None, "empty"
    bad = communities.ungrounded_numbers(text, report)
    if bad:
        return None, f"ungrounded_numbers: {bad}"
    return text, "ok"


def build() -> list[dict]:
    store.reload()
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    reports = communities.build_reports()

    n_llm = 0
    for r in reports:
        text, status = _llm_narrative(r)
        if text:
            r["narrative_ja"] = text
            r["narrative_source"] = "llm"
            n_llm += 1
        else:
            # Keep the deterministic templated narrative already on the report.
            r["narrative_source"] = "template"
        r["grounded"] = True  # every narrative (llm-verified or templated) is grounded
        print(f"  {r['id']:32s} [{r['narrative_source']:8s}] {status if not text else 'ok'}")

    config.COMMUNITIES_PATH.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "model": config.MODEL,
        "today": config.today().isoformat(),
        "counts": {"segments": len(reports), "llm": n_llm, "template": len(reports) - n_llm},
    }
    (config.INDEX_DIR / "communities.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    communities.reload()
    print(f"\nwrote {config.COMMUNITIES_PATH.name}: {len(reports)} segments "
          f"({n_llm} LLM narratives, {len(reports) - n_llm} templated)")
    return reports


if __name__ == "__main__":
    build()
