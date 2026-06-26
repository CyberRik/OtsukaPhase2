# Phase 2.5 — latency, model decomposition & the synthesis architecture

An engineering log of the session that took Senpai's tool-loop from "correct but
slow" toward a latency-first serving architecture. It documents what we **tried**,
what the **data** said, and the **decisions** — including the ideas we rejected and
why, so they aren't re-litigated. Companion to
[`phase25_session_log.md`](phase25_session_log.md) (earlier Phase-2.5 work) and
[`llm_bridge.md`](llm_bridge.md) (the bridge/serving baseline).

> TL;DR — the latency sink was never tool execution or retrieval (<1%); it was the
> 27B doing **two** generations per turn (a discarded answer in the tool loop, then
> synthesis) and the **synthesis** itself. We now serve **all synthesis on a Q4 8B**
> (~3× faster) and keep **tool selection on the 27B** (the 8B can't tool-call
> reliably). PPT/proposal generation, ambiguity, and grounding are preserved.

---

## 1. Serving setup & the 93 GB ghost

- **Q4 8B added.** `Qwen3-8B-Q4_K_M.gguf` (~5 GB) served via `llama-server` on the
  GB10 box, port **:8766**, alias **`qwen3-8b`**. The 27B stays on :8765. Both are
  reachable **directly over Tailscale** (`100.101.186.29:8765/8766`) — the SSH
  tunnel is optional, not required (the old "`:8765` firewalled" note is stale).
- **The memory crunch was an outside process.** Every OOM/"models don't coexist"
  symptom traced to a **teammate's Docker container `atlas`** (`avarok/atlas-gb10`,
  `spark serve` a 35B model) holding **~93 GB** of the 119 GB unified memory —
  invisible to `ps`/`free`, only visible via
  `nvidia-smi --query-compute-apps=pid,used_memory`. After `docker stop atlas`:
  5.8 GB used / 113 GB free. Both our models fit with ~90 GB to spare. The box is
  **shared**; check `nvidia-smi`/`docker ps` before blaming our servers.
- **Network resilience.** A self-healing tunnel (auto-reconnect loop) was used for
  the local dev box; long benchmarks were made crash-proof with per-query
  checkpointing + retry after the network dropped tunnels mid-run twice.

---

## 2. Model-decomposition benchmark (synthesis on a smaller model)

**Question:** can the final grounded **synthesis** be served by the 8B without
losing grounding/quality, for a latency win? **Method:** frozen-context A/B —
freeze the 27B's post-tool context once, synthesize the *identical* context on each
arm (`scripts/bench_synthesis.py`).

| Round | Candidate | Speedup | Grounding |
|---|---|---|---|
| 1 | **bf16** 8B | 1.11× | parity |
| 2 | **Q4_K_M** 8B (n=2) | **2.72×** wall, 3.8× decode | parity (0.969 = 0.969) |

bf16 was bandwidth-bound (same bytes/token as Q4-27B); **Q4** was the needed lever
(~3× fewer bytes/token). Decode: 8B ~35 tok/s vs 27B ~10.5 tok/s.

**Quality is the catch — not grounding, *style*.** The 8B kept facts but read more
mechanically (bullet-dumps, repeated fields) vs the 27B's mentorship narrative.

---

## 3. Can prompting close the style gap? (so the 8B does *everything*)

**Audit:** there was no dedicated synthesis prompt — the 8B inherited the tool-use
role prompt, which has one line of tone guidance and literally instructs
enumeration (`列挙は箇条書きにし`). Under-prompted for style.

**Built** `senpai/llm/synth_style.py` — a style booster (prioritise over enumerate,
abstract over repeat, merge redundancy, mentor voice, grounding clause) + optional
few-shot exemplar, injected **only** when the 8B synthesises. **Evaluated** with
`scripts/bench_synth_prompt.py` (frozen-context, 4 arms, FAST+THINK, 27B judge).

**Pilot (n=4) looked great, then the larger run overturned it.** On **n=8 FAST**:

| Arm | Latency | Judge 8B / 27B | Wins (8b/27b) | Note |
|---|---|---|---|---|
| control (27B) | 52 s | — (bar) | — | |
| 8b_plain | 21 s | 3.25 / 4.75 | 1 / 7 | grounding-safe |
| 8b_style | 22 s | 3.50 / 4.50 | 2 / 6 | over-abstracts |
| 8b_fewshot | 16 s | 3.50 / 4.25 | 3 / 5 | best, still loses; **drops facts** (specificity 7.8 vs 23.8) |

**Verdict:** prompting did **not** close the gap on the larger sample — every 8B
arm trails the 27B on judged coaching quality, and few-shot trades grounding
specificity for prose. The n=4 "8B beats 27B" was small-sample noise. *(THINK-arm
validation was cut short to focus on latency.)* So "8B for everything on quality
grounds" is **not** supported — but it **is** acceptable under a latency-first
policy (below).

---

## 4. Where the latency actually goes (profiling, not guessing)

`scripts/profile_selection.py` instruments each component of a turn (server
`timings` separate GPU decode / prompt-eval / network). Across 6 workflows:

- **LLM generation = 98%** of wall time. **Tool execution 0.8%, retrieval/net ~1%.**
  So the model is the cost — *not* tool execution or retrieval.
- **Within the LLM time, the final-answer generation dominates** (e.g. C28: 22.9 s
  selection vs **91.9 s** answer). The earlier "selection = 130 s" was a
  misattribution — it lumped the answer round into selection.
- Decode is a flat ~10.5 tok/s (memory-bandwidth-bound) → time ≈ tokens ÷ 10.5.

**The real villain: double-generation.** The tool loop's selection `create()`
(`tool_choice="auto"`) generates the **entire answer** just to signal "no more
tools" — that answer is **discarded**, then the synthesis round generates it
**again**. Real turns paid for the answer ~twice on the 27B (~200 s research turns).

---

## 5. Killing the double-generation — two failures, then the fix

| Attempt | Idea | Result |
|---|---|---|
| ❌ cap | `max_tokens` on the selection round | Truncated long tool calls (PPTX/proposal payloads, whose `<think>` eats the budget) → llama-server **500 "Failed to parse tool call arguments as JSON"**. Reverted. |
| ❌ stream-abort | stream selection, abort when answer-prose starts | Broke tools that emit a **prose preamble before the tool call** (PPT narrated instead of calling). Reverted. |
| ✅ **finish-tool** | `tool_choice="required"` + a `finish` sentinel tool | The model **always** emits a tool call (real or `finish`); selection never generates a throwaway answer, and tool calls always complete (no truncation, no abort). |

**finish-tool pattern** (`senpai/llm/client.py`): a `_FINISH_TOOL` is appended to
the chat-loop tools; selection runs with `tool_choice="required"`. Real tool calls
execute and loop; `finish` (or no real tool) ends the loop → the single routed
synthesis round. Smoke-tested across all 7 workflows: **all correct, PPT fixed, no
500s**, pure-chat calls `finish` immediately.

---

## 6. Latency-first policy: all synthesis on the 8B; selection stays on the 27B

finish-tool removed the double-gen, but THINK-routed workflows were still slow
(create_quote 334 s, schedule 366 s) because they did **full 27B THINK synthesis**.
Per the explicit "latency over accuracy" call, we route **all** synthesis to the 8B
(`SENPAI_SYNTH_ALL_8B=1`): create_quote **334 → 152 s**.

**Then tested 8B for *selection* too** — and it failed:

| Query | 8B emitted |
|---|---|
| C28 past deals | **no tool call** |
| MFP30 quote | **no tool call** |
| D168 PPT | `generate_proposal` ✓ |
| schedule meeting | `schedule_meeting` ✓ |
| greeting | `morning_briefing` (**wrong**, should be `finish`) |

Only **2/5** reliable. A **hybrid** (8B-first, 27B-fallback) is also a net loss: the
8B fails on the majority, so the wasted-attempt-then-retry penalty makes ~3/5 turns
*slower*. **Conclusion: tool selection must stay on the 27B.** The data said "don't
put the tool loop on the 8B" three different ways (the cap 500, the prompt-eval
profile, and this reliability test).

### Final architecture

| Stage | Model | Why |
|---|---|---|
| Tool selection (finish-tool loop) | **27B** | only reliable tool-caller |
| Synthesis (FAST **and** THINK) | **8B Q4** | ~3× faster; quality cost accepted |

This is the **safe latency floor** for the current two models. Further speed needs a
*different* lever (a smaller model that's actually reliable at tool-calling, or
faster 27B serving — it's bandwidth-bound), not a config flag.

---

## 7. Live configuration (`.env`)

```env
BASE_URL="http://127.0.0.1:8765/v1"          # 27B (selection + failover), via tunnel
MODEL="Qwen3.6-27B-Claude-Opus-Reasoning-Distilled"
SENPAI_FAST_SYNTH_FALLBACK=1                  # FAST synthesis → 8B
SENPAI_SYNTH_ALL_8B=1                         # ALL synthesis → 8B (latency-first)
FALLBACK_BASE_URL="http://100.101.186.29:8766/v1"   # 8B, direct over Tailscale
FALLBACK_MODEL="qwen3-8b"
LLM_TIMEOUT=300
```

Knobs (all reversible): `SENPAI_SYNTH_ALL_8B=0` → hybrid (FAST→8B, THINK→27B);
`SENPAI_FAST_SYNTH_FALLBACK=0` → everything back on the 27B. Routing lives in
`senpai/llm/client.py::_synth_route`; a `synth` SSE event surfaces which tier wrote
each answer.

---

## 8. Other fixes this session

- **Case-insensitive customer/deal IDs.** `/account c21` returned "not found"
  though C21 exists — `get_customer`/`get_deal` did exact (uppercase) dict lookups.
  Now they fall back to `.upper()`, so `c21`/`d128` resolve like `C21`/`D128`
  (`senpai/data/store.py`).
- **"Enter" send button.** The workspace send button ("Show the Coach" / "Ask
  Analyst") is now **"Enter"** for both roles, both languages (`web/lib/i18n.tsx`:
  `chat.send`, `chat.send.manager`).
- **`/research` deal-picker (noted, not changed).** A customer-level research query
  ("research about C14") is short-circuited to a deal picker whenever the customer
  has >1 open deal, because the research bundle is built **per-deal**. Working as
  coded, but arguably too deal-centric for an account-level ask — candidate fix: a
  customer-level bundle aggregating all open deals.

---

## 9. Artifacts added

| File | Purpose |
|---|---|
| `senpai/llm/synth_style.py` | 8B synthesis-style booster + few-shot (§3) |
| `senpai/llm/client.py` | `_synth_route`, `_FINISH_TOOL` + finish-tool loop (§5–6) |
| `scripts/bench_synth_prompt.py` | 4-arm prompt/style A/B with 27B judge (§3) |
| `scripts/rejudge_synth.py` | re-run only the judge over cached answers |
| `scripts/profile_selection.py` | per-component selection-phase profiler (§4) |
| Box: `~/Desktop/qwen3-8b-gguf/serve_8b_gguf.sh` | serve the Q4 8B on :8766 |

---

## 10. Open items / recommendations

1. **Verify the 8B-synthesis quality at the demo level** — judged lower than the
   27B; acceptable under latency-first, but spot-check real coaching turns.
2. **THINK-arm prompt validation** was cut short — if quality matters later, finish
   the n≥16 THINK comparison before trusting all-8B on reasoning turns.
3. **Reliable small tool-caller** is the only path to faster *selection*; the
   current 8B can't, and hybrid selection is net-slower.
4. **`/research` account-level aggregation** (§8) if customer-level research matters.
