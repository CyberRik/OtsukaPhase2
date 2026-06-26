"""Profile the tool-SELECTION phase: where does the ~130s actually go?

For each query we run the real chat tool-selection loop (same as
senpai.llm.client.stream_chat_turn / bench_synthesis.freeze_context) and time
every component separately:

  * intent/resolution  — customer-match + research-intent regex (pre-loop)
  * llm_gen            — the model's tool-selection generation, split into:
       server_prompt_ms  (prompt eval on the GPU)
       server_predict_ms (decode on the GPU)         <- the "reasoning" cost
       net_overhead      (wall - server time = queue/network/transport)
  * tool_exec          — dispatch() per tool (store lookups + retrieval inside)
  * tokens + decode tok/s per round

llama-server returns per-request `timings` (prompt_ms / predicted_ms / *_per_second)
in the response body; the OpenAI SDK exposes them on `.model_extra`. That lets us
attribute wall time to GPU-generation vs everything else — the whole question.

Run (27B must be idle for a clean read):
  python scripts/profile_selection.py [--model MODEL] [--base BASE_URL]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Chat tool-loop queries — the ONLY path with an LLM selection phase. (/review,
# /account, /research are deterministic skills with no tool-selection loop.)
QUERIES = [
    ("C28について、過去の案件と最近のやり取りを教えて", "junior", "multi-tool data"),
    ("need more research about C28, look at all past deals and what to expect?", "junior", "multi-tool research"),
    ("決裁者に会えないときはどう対応すべき？", "junior", "knowledge/coaching"),
    ("MFP30を2台で見積を作って", "junior", "create_quote"),
    ("明日15時に丸三食品と会議を設定して", "junior", "schedule_meeting"),
    ("いま危ない案件を挙げて、共通の原因は？", "manager", "at-risk (manager)"),
]


def _timings(resp):
    """Pull llama-server's per-request timings off the SDK response, if present."""
    t = getattr(resp, "model_extra", None) or {}
    tim = t.get("timings") if isinstance(t, dict) else None
    if not tim:
        tim = getattr(resp, "timings", None)
    return tim or {}


def profile_query(query, role, client, model):
    from senpai import config
    from senpai.tools.impl import dispatch
    from senpai.llm.client import _prep, _fmt_args
    from senpai.api import server
    from senpai.data import store

    # --- pre-loop: intent / resolution (regex, GPU-free) ---
    t0 = time.perf_counter()
    _ = store.match_customer_in_text(query)
    _ = server._is_research_intent(query)
    intent_s = time.perf_counter() - t0

    tools, sysfn = server._CHAT_ROLES.get(role, server._CHAT_ROLES["junior"])
    convo = [{"role": "system", "content": sysfn()}, {"role": "user", "content": query}]

    rounds = []
    tool_exec_total = 0.0
    llm_wall_total = 0.0
    for _r in range(config.MAX_TOOL_ROUNDS):
        tw0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=model, messages=_prep(convo, False), tools=tools,
            tool_choice="auto", temperature=0.0)
        llm_wall = time.perf_counter() - tw0
        llm_wall_total += llm_wall
        tim = _timings(resp)
        u = resp.usage
        pt = u.prompt_tokens if u else None
        ct = u.completion_tokens if u else None
        p_ms = tim.get("prompt_ms"); d_ms = tim.get("predicted_ms")
        server_s = ((p_ms or 0) + (d_ms or 0)) / 1000.0
        rounds.append({
            "llm_wall_s": round(llm_wall, 2),
            "server_prompt_ms": round(p_ms, 1) if p_ms else None,
            "server_predict_ms": round(d_ms, 1) if d_ms else None,
            "net_overhead_s": round(llm_wall - server_s, 2) if server_s else None,
            "prompt_tokens": pt, "completion_tokens": ct,
            "decode_tok_s": round(tim.get("predicted_per_second"), 1) if tim.get("predicted_per_second") else None,
        })
        msg = resp.choices[0].message
        if not msg.tool_calls:
            break
        calls = [(tc.id, tc.function.name, tc.function.arguments) for tc in msg.tool_calls]
        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": n, "arguments": a}}
            for cid, n, a in calls]})
        for cid, name, args in calls:
            te0 = time.perf_counter()
            result = dispatch(name, args)
            te = time.perf_counter() - te0
            tool_exec_total += te
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})
            rounds[-1].setdefault("tools", []).append(
                {"name": name, "exec_s": round(te, 3), "args": _fmt_args(args)[:40]})

    server_gen = sum((r["server_predict_ms"] or 0) for r in rounds) / 1000.0
    server_prompt = sum((r["server_prompt_ms"] or 0) for r in rounds) / 1000.0
    net = sum((r["net_overhead_s"] or 0) for r in rounds)
    total = intent_s + llm_wall_total + tool_exec_total
    return {"query": query, "role": role, "n_rounds": len(rounds),
            "intent_s": round(intent_s, 3),
            "llm_gen_decode_s": round(server_gen, 1),
            "llm_prompt_eval_s": round(server_prompt, 1),
            "net_overhead_s": round(net, 1),
            "tool_exec_s": round(tool_exec_total, 3),
            "llm_wall_s": round(llm_wall_total, 1),
            "total_s": round(total, 1),
            "comp_tokens": sum((r["completion_tokens"] or 0) for r in rounds),
            "prompt_tokens_last": rounds[-1]["prompt_tokens"] if rounds else None,
            "rounds": rounds}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    from senpai import config
    from openai import OpenAI
    base = args.base or config.BASE_URL
    model = args.model or config.MODEL
    client = OpenAI(base_url=base, api_key="dummy", timeout=600)
    print(f"profiling selection on model={model} base={base}\n")

    rows = []
    for q, role, tag in QUERIES:
        print(f"[{tag}] {q[:50]}")
        r = profile_query(q, role, client, model)
        rows.append({**r, "tag": tag})
        print(f"   rounds={r['n_rounds']}  TOTAL={r['total_s']}s")
        print(f"     intent/resolve : {r['intent_s']}s")
        print(f"     LLM decode     : {r['llm_gen_decode_s']}s   (the 'reasoning' generation)")
        print(f"     LLM prompt-eval: {r['llm_prompt_eval_s']}s")
        print(f"     net/queue      : {r['net_overhead_s']}s")
        print(f"     tool execution : {r['tool_exec_s']}s")
        print(f"     comp tokens={r['comp_tokens']}  last prompt tokens={r['prompt_tokens_last']}")
        for i, rd in enumerate(r["rounds"], 1):
            tl = ",".join(t["name"] for t in rd.get("tools", [])) or "(answer)"
            print(f"       r{i}: wall={rd['llm_wall_s']}s decode={rd['decode_tok_s']}t/s "
                  f"ct={rd['completion_tokens']} -> {tl}")
        print()

    # aggregate attribution
    agg = {k: round(sum(r[k] for r in rows), 1) for k in
           ("intent_s", "llm_gen_decode_s", "llm_prompt_eval_s", "net_overhead_s", "tool_exec_s", "total_s")}
    print("=== AGGREGATE ATTRIBUTION (sum over queries) ===")
    print(json.dumps(agg, indent=2))
    gen = agg["llm_gen_decode_s"] + agg["llm_prompt_eval_s"]
    print(f"\nLLM (decode+prompt-eval) = {gen}s of {agg['total_s']}s "
          f"= {round(100*gen/agg['total_s'])}%  |  tool_exec = "
          f"{round(100*agg['tool_exec_s']/agg['total_s'],1)}%  |  net = "
          f"{round(100*agg['net_overhead_s']/agg['total_s'])}%")
    out = Path(__file__).resolve().parent / "profile_selection_results.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nfull -> {out}")


if __name__ == "__main__":
    main()
