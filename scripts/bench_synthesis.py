"""A/B benchmark: 27B synthesis vs a smaller synthesis model (model decomposition).

Tests the recommendation in the model-decomposition plan: can the FINAL grounded
synthesis be served by a smaller model (Qwen3-8B) without materially reducing
quality, for a large latency win?

Design (the methodology that must be right):
  * FREEZE TOOL OUTPUTS. For each query we run the 27B's tool-SELECTION rounds +
    execute the tools ONCE (deterministic), then feed the *identical* post-tool
    context to BOTH synthesis models. This isolates the synthesis-model variable
    and removes tool-selection nondeterminism — the only thing that differs
    between arms is who writes the final answer.
  * Control   : 27B (select) -> tools -> 27B (synthesis)
  * Candidate : 27B (select) -> tools -> 8B (synthesis)   [same frozen context]
  * The reasoning router decides no_think per query; BOTH arms use the same flag,
    so we compare like-for-like (FAST restatement vs THINK interpretation).

Metrics (per query + aggregate):
  * latency (wall), prompt tokens, completion tokens, decode tok/s
  * grounding fidelity   — every ¥amount / C-id / D-id / date / source-id in the
                           answer must appear in the frozen tool context; anything
                           that doesn't is a candidate FABRICATION (hard signal).
  * provenance           — source ids (PBxx / Pxxx) cited must exist in context
  * coaching quality     — answers are dumped side-by-side for blind review; an
                           optional --judge pass scores pairwise with the 27B.

NOTHING in the live request path is touched. Run once:
  python scripts/bench_synthesis.py --candidate-base http://127.0.0.1:8766/v1 \
         --candidate-model qwen3-8b [--queries 6] [--judge]

Endpoints: control defaults to senpai config (BASE_URL/MODEL, the 27B on :8765
via the SSH tunnel); candidate is the 8B (serve with vLLM on :8766, tunnel it).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root -> import senpai

import numpy as np


# --- benchmark queries: grounded, real customers/deals, FAST + THINK regimes ---
# (query, role, regime_hint) — regime_hint is documentation; the router decides.
QUERIES: list[tuple[str, str, str]] = [
    # FAST — grounded summarization of records (the decomposition target)
    ("need more research about C14, look at all past deals and what to expect?", "junior", "fast"),
    ("丸三食品の案件の状況と直近のやり取りを教えて", "junior", "fast"),
    ("株式会社松田サービス（C28）の取引履歴をまとめて", "junior", "fast"),
    ("C100の案件と最近の日報を確認したい", "junior", "fast"),
    ("D027の顧客のIT環境と過去の活動を整理して", "junior", "fast"),
    # THINK — numeric / cross-signal interpretation (should stay on 27B)
    ("D027の案件健全度を評価して、リスクと次の一手を教えて", "junior", "think"),
    ("丸三食品は接触は多いが前進しない。なぜか、どうすべきか分析して", "junior", "think"),
    ("いま危ない案件を挙げて、何が共通の原因か考えて", "manager", "think"),
]


def _make_client(base_url: str):
    from openai import OpenAI
    return OpenAI(base_url=base_url, api_key="dummy")


# --- Phase 1: freeze the post-tool context using the 27B selection loop --------
def freeze_context(query: str, role: str, ctrl_client, ctrl_model: str):
    """Run the 27B tool-SELECTION rounds + execute tools, returning the convo just
    BEFORE synthesis. Mirrors senpai.llm.client.stream_chat_turn's selection loop
    but stops at the answering round instead of synthesizing."""
    from senpai import config
    from senpai.tools.impl import dispatch
    from senpai.llm.client import _prep, _fmt_args
    from senpai.api import server

    tools, sysfn = server._CHAT_ROLES.get(role, server._CHAT_ROLES["junior"])
    convo = [{"role": "system", "content": sysfn()}, {"role": "user", "content": query}]
    tool_log: list[tuple[str, str, str]] = []
    t0 = time.perf_counter()
    for _ in range(config.MAX_TOOL_ROUNDS):
        resp = ctrl_client.chat.completions.create(
            model=ctrl_model, messages=_prep(convo, False), tools=tools,
            tool_choice="auto", temperature=0.0)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            break  # answering round reached — stop; synthesis is the benchmarked part
        calls = [(tc.id, tc.function.name, tc.function.arguments) for tc in msg.tool_calls]
        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": n, "arguments": a}}
            for cid, n, a in calls]})
        for cid, name, args in calls:
            result = dispatch(name, args)
            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})
    sel_s = time.perf_counter() - t0

    # routed reasoning mode for the synthesis round (same flag for both arms)
    from senpai.llm.routing import get_reasoning_router, RoutingRequest
    dec = get_reasoning_router().route(RoutingRequest(
        message=query, role=role, tools_used=[n for n, _a, _r in tool_log],
        rounds=len(tool_log)))
    grounding = "\n".join(r for _n, _a, r in tool_log)  # what the answer must stay within
    return {"convo": convo, "tool_log": tool_log, "no_think": not dec.think,
            "mode": "think" if dec.think else "fast", "select_s": sel_s,
            "tools": [n for n, _a, _r in tool_log], "grounding": grounding}


# --- Phase 2: synthesize on one model from a frozen context -------------------
_THINK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>|<think(?:ing)?>", re.DOTALL | re.IGNORECASE)


def synthesize(client, model: str, frozen: dict):
    from senpai.llm.client import _prep
    msgs = _prep(frozen["convo"], frozen["no_think"])
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model, messages=msgs, temperature=0.0, max_tokens=1024)
    dt = time.perf_counter() - t0
    m = resp.choices[0].message
    text = _THINK.sub("", m.content or "").strip()
    u = resp.usage
    comp = u.completion_tokens if u else len(text) // 3
    return {"text": text, "wall_s": round(dt, 1),
            "prompt_tokens": u.prompt_tokens if u else None,
            "completion_tokens": comp,
            "tok_s": round(comp / dt, 1) if dt else 0.0}


# --- Phase 3: automatable grounding / provenance checks -----------------------
_PATTERNS = {
    "yen": re.compile(r"¥[\d,]+"),
    "customer_id": re.compile(r"\bC\d{1,4}\b"),
    "deal_id": re.compile(r"\bD\d{3}\b"),
    "source_id": re.compile(r"\b(?:PB\d+|P\d{3})\b"),
    "date": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "bignum": re.compile(r"\b\d{3,}\b"),  # counts / amounts written without ¥
}


def grounding_report(answer: str, context: str) -> dict:
    """Every factual token the answer states must be traceable to the frozen tool
    context. Unsupported tokens are candidate fabrications (the veto metric)."""
    ctx = context
    # normalize ¥ amounts (drop commas) so '¥960,000' matches '960000' in records
    ctx_norm = ctx.replace(",", "")
    unsupported: list[str] = []
    checked = 0
    for kind, pat in _PATTERNS.items():
        for tok in set(pat.findall(answer)):
            checked += 1
            t_norm = tok.replace(",", "").lstrip("¥")
            if t_norm not in ctx_norm and tok not in ctx:
                unsupported.append(f"{kind}:{tok}")
    return {"checked": checked, "unsupported": unsupported,
            "fidelity": round(1 - len(unsupported) / checked, 3) if checked else 1.0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-base", default="http://127.0.0.1:8766/v1")
    ap.add_argument("--candidate-model", default="qwen3-8b")
    ap.add_argument("--queries", type=int, default=len(QUERIES))
    ap.add_argument("--out", default="scripts/bench_synthesis_results.json")
    args = ap.parse_args()

    from senpai import config
    from senpai.llm.client import client as ctrl_client  # 27B primary (:8765)
    ctrl_model = config.MODEL
    cand_client = _make_client(args.candidate_base)
    qs = QUERIES[: args.queries]

    print(f"control:   {config.BASE_URL}  model={ctrl_model}")
    print(f"candidate: {args.candidate_base}  model={args.candidate_model}")
    print(f"queries:   {len(qs)}\n")

    rows = []
    for i, (q, role, hint) in enumerate(qs, 1):
        print(f"[{i}/{len(qs)}] ({hint}) {q[:50]}…")
        fr = freeze_context(q, role, ctrl_client, ctrl_model)
        print(f"    selection {fr['select_s']:.0f}s, tools={fr['tools']}, mode={fr['mode']}")
        ctrl = synthesize(ctrl_client, ctrl_model, fr)
        print(f"    27B  {ctrl['wall_s']}s  {ctrl['completion_tokens']}tok  {ctrl['tok_s']}tok/s")
        cand = synthesize(cand_client, args.candidate_model, fr)
        print(f"    8B   {cand['wall_s']}s  {cand['completion_tokens']}tok  {cand['tok_s']}tok/s")
        g_ctrl = grounding_report(ctrl["text"], fr["grounding"])
        g_cand = grounding_report(cand["text"], fr["grounding"])
        rows.append({"query": q, "role": role, "hint": hint, "mode": fr["mode"],
                     "tools": fr["tools"], "select_s": round(fr["select_s"], 1),
                     "control": {**ctrl, "grounding": g_ctrl},
                     "candidate": {**cand, "grounding": g_cand}})
        print(f"    grounding fidelity  27B={g_ctrl['fidelity']}  8B={g_cand['fidelity']}"
              f"   (8B unsupported: {g_cand['unsupported'] or 'none'})")

    # aggregate
    def agg(arm, key):
        vals = [r[arm][key] for r in rows if r[arm].get(key) is not None]
        return round(float(np.mean(vals)), 1) if vals else None
    summary = {
        "n": len(rows),
        "control": {"avg_wall_s": agg("control", "wall_s"),
                    "avg_completion_tokens": agg("control", "completion_tokens"),
                    "avg_tok_s": agg("control", "tok_s"),
                    "avg_fidelity": round(float(np.mean([r["control"]["grounding"]["fidelity"] for r in rows])), 3)},
        "candidate": {"avg_wall_s": agg("candidate", "wall_s"),
                      "avg_completion_tokens": agg("candidate", "completion_tokens"),
                      "avg_tok_s": agg("candidate", "tok_s"),
                      "avg_fidelity": round(float(np.mean([r["candidate"]["grounding"]["fidelity"] for r in rows])), 3)},
    }
    spd = (summary["control"]["avg_wall_s"] / summary["candidate"]["avg_wall_s"]
           if summary["candidate"]["avg_wall_s"] else None)
    summary["synthesis_speedup_x"] = round(spd, 2) if spd else None

    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nfull results + side-by-side answers -> {args.out}")
    print("Review the answers in the JSON for coaching-quality / tone before deciding.")


if __name__ == "__main__":
    main()
