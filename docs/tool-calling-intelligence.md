# Intelligent Tool Calling & Loop Prevention

In standard ReAct-style LLM agents, it is extremely common for the model to get stuck in a "tool loop" — rephrasing the same failed search, repeating an action, or burning turns with throwaway answers until it hits the hard limit (e.g., `MAX_TOOL_ROUNDS = 10`) and crashes.

To prevent this and keep latency low, `senpai/llm/client.py` implements a series of intelligent control-flow defenses. This guarantees the model safely exits the loop and synthesizes an answer without exhausting its context window or API limits.

---

## 1. The `finish` Sentinel (Zero Throwaway Answers)
Typically, if a model wants to stop using tools, it generates a plain text answer. If you enforce `tool_choice="required"` to prevent premature answering, the model often invents a fake tool call or hallucinates.

**How we solve this:**
We inject a sentinel tool called `finish` and enforce `tool_choice="required"` on every reasoning round.
- The model *must* call a tool.
- When it has enough information, it calls `finish`.
- We intercept `finish` (it is never dispatched to the engine) and instantly break the loop, advancing to the final synthesis round. This saves the latency and context of a "dummy" turn.

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
- **Truncation**: Any single tool result exceeding 1500 characters is aggressively truncated (`... [truncated for length]`), keeping the context buffer safe.
- **Substantive Fallback**: The loop tracks `substantive` tool results (ignoring errors or "not found"). If the final synthesis round fails or emits an empty `<think>` block, the agent automatically surfaces the last substantive tool output (e.g., the raw data from the CRM) so the user never sees a blank `(no response)`.
