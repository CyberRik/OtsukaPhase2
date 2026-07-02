# Intelligent Tool Calling & Loop Prevention

In standard ReAct-style LLM agents, it is extremely common for the model to get stuck in a "tool loop" — rephrasing the same failed search, repeating an action, or burning turns with throwaway answers until it hits the hard limit (e.g., `MAX_TOOL_ROUNDS = 10`) and crashes.

To prevent this and keep latency low, `senpai/llm/client.py` implements a series of intelligent control-flow defenses. This guarantees the model safely exits the loop and synthesizes an answer without exhausting its context window or API limits.

---

## 1. The `finish` Sentinel (Zero Throwaway Answers)
Typically, if a model wants to stop using tools, it generates a plain text answer. If you enforce `tool_choice="required"` to prevent premature answering, the model often invents a fake tool call or hallucinates.

**How we solve this:**
We inject a sentinel tool called `finish` and force a tool call on the **first** round.
- On the first round `tool_choice="required"` — the model *must* gather before it can answer, and can't burn the round on a throwaway reply.
- When it has enough information, it calls `finish` (or, on later rounds, simply emits no tool call).
- We intercept `finish` (it is never dispatched to the engine) and instantly break the loop, advancing to the final synthesis round. This saves the latency and context of a "dummy" turn.

> **Once evidence exists, `tool_choice` relaxes to `"auto"`** (`tool_choice = "required" if not tool_log else "auto"`). Forcing `required` on *every* round is what pressures the model into contorting its final answer into a bogus tool argument instead of finishing cleanly — see §6. Round-0 stays `"required"` for the gather guarantee; the parallelism this costs is not real here anyway (see §7).

## 2. Anti-Spiraling (`_TOOL_ROUND_CAP`)
A model might search for `X`, not find it, and try searching for `Y`, `Z`, `W` across multiple rounds. This burns through the 10-call limit quickly.

**How we solve this:**
We track how many *rounds* a specific tool has been used in. If a tool (e.g., `search_notes`) appears in more than `_TOOL_ROUND_CAP` (default 2) rounds, it is considered a spiral.
- The next time the model calls it, the call is **intercepted and short-circuited**.
- We return a nudge to the model: `（取得済み。これ以上検索せず、収集済みの情報で回答してください。）` ("Already obtained. Do not search further, answer with collected info").
- *Note: This limits rounds, not fan-out. A single round can still parallel-call `web_search` 4 times successfully.*

## 3. Terminal Actions
When a model is asked to "create a deck", it might successfully generate the PPTX on round 1, but then decide to check its work and call `generate_pptx` *again* on round 2, producing duplicates.

**How we solve this:**
`_is_terminal_action()` flags tools that produce deliverables (`schedule_meeting`, `create_quote`, `send_email`, `generate_*`).
- If an action tool successfully commits (i.e., not a dry-run preview, and not an error), the tool loop **hard-terminates immediately**.
- The turn ends and the deliverable's success message is streamed to the user, bypassing the redundant synthesis round completely.

## 4. Exact Deduplication
If the model calls the exact same tool with the exact same arguments in the same turn, it wastes backend resources and context space.
- We use `_canon_args()` to normalize JSON arguments (sorting keys and normalizing whitespace).
- Duplicate calls are skipped and instantly fed the cached result from the first execution.

## 5. Context Truncation & Fallbacks
10 tool calls—especially parallel searches—can easily blow up a 32k context window, causing the final synthesis round to OOM or emit a blank answer.
- **Truncation**: Any single tool result exceeding 1500 characters is aggressively truncated on a natural boundary (`_truncate_on_boundary`, so a company name or ¥ figure is never severed mid-token), keeping the context buffer safe.
- **Substantive Fallback**: The loop tracks `substantive` tool results (ignoring errors or "not found"). If the final synthesis round fails or emits an empty `<think>` block, the agent automatically surfaces the last substantive tool output (e.g., the raw data from the CRM) so the user never sees a blank `(no response)`.

## 6. The Answer-as-Arg Leak Guard (`_is_finish_leak`)
Under forced `tool_choice="required"`, a reasoning-distill model that is *ready to answer* but obliged to emit a tool call will sometimes **pack its entire final answer into a tool argument** — e.g. `query_spr(customer="**結論：…**\n| table |\n…<tool_call>\n<function=finish>")`. Observed live on a "compare D016 vs D100" turn. This is doubly expensive: it dispatches a bogus query (that giant string fuzzy-matched *all* deals for the customer), **and** the turn generates the full answer twice — once as the leaked argument, once at real synthesis.

**How we solve this:**
- Relaxing `tool_choice` to `"auto"` after the first round (§1) removes most of the pressure that causes the leak — the model can just stop.
- As a belt-and-braces guard, `_is_finish_leak(name, args)` drops any call whose arguments carry a stray finish/think/tool_call marker (`function=finish`, `<tool_call>`, `</think>`, `</function>`) or an answer-sized argument blob (>600 chars; real args like `{"deal_id":"D016"}` are tiny). If nothing real remains after filtering, the model is effectively done → the loop routes to **one clean synthesis** instead of a wasted round plus a double generation.

## 7. Parallel Fan-Out — capability, prompt suppression, and where it actually pays off
Parallelism exists in the infrastructure: the `AdaptiveScheduler` builds a DAG where every `parallel_safe` **read** runs concurrently and only WRITE/EXTERNAL tools serialize behind a barrier (`senpai/orchestration/scheduler.py`), and the engine fans out all fresh calls from a round in one plan. This helps *only* when the model emits several `tool_calls` **in a single response**.

**The model *can* batch — in isolation (measured).** A direct probe of atlas-35b on an explicit "call BOTH D016 and D100 now":

| `tool_choice` | thinking | tool_calls returned |
| :-- | :-- | :-- |
| `auto` | off | **2** (D016 + D100) |
| `auto` | on | 1 |
| `required` | off | 1 |
| `required` | on | 1 |

So batching needs `tool_choice="auto"` + thinking-off; `required` triggers XGrammar structural enforcement that caps output at a single `<tool_call>`.

**But the full operational prompt suppresses it — and that's decisive.** Mirroring the real round-0 request (same query, `auto`, thinking-off) but varying the system prompt:

| system prompt | tool_calls |
| :-- | :-- |
| minimal | **2** |
| full `_junior_system()` | **1** |

The junior prompt *already contains* an explicit "batch independent lookups in one turn" instruction, and adding a stronger one changed nothing — the weight of the full grounding-first prompt makes the model emit one call regardless. Batching only reappears if you strip the prompt down, which would sacrifice the gather/grounding guarantees the prompt exists to enforce. **That trade — gutting a correctness-critical prompt to save ~1 round — is not worth it**, so we do not chase in-chat batching. (This is also why round-0 stays `"required"`: the parallelism it "costs" isn't obtainable here anyway.)

**Where deterministic parallelism is available today:** the orchestration / LLM-planner path, not the chat ReAct loop. A plan can declare multiple independent tasks up front, which the engine runs concurrently — independent of the model's in-chat batching behavior. Structured multi-entity workflows (e.g. account intelligence comparing several deals) should go through that path when fan-out latency matters.
