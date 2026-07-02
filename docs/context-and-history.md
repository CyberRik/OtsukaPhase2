# Managing Context and History in Chat

Maintaining conversational memory is a multi-layered problem. We not only have to remember what was said, but we must also ensure that **background tools** (like a slide deck generator running on a parallel thread) have access to that exact same conversational context so they don't hallucinate facts.

Here is how history and context are maintained across the application.

---

## 1. The Standard Chat Loop (`convo` Object)
In `senpai/llm/client.py`, the conversation history is passed into `stream_chat_turn` as a mutable list of dictionaries (the standard OpenAI `messages` format). 
- As the model executes tool calls (e.g., retrieving a CRM record or searching the web), the tool requests and their actual results are appended **in-place** to the `convo` object.
- Because the results stay in the message history, the LLM naturally remembers the facts it gathered from previous turns and previous loops without needing to re-fetch them.

## 2. Router Memory (Stateful Affirmations)
Sometimes the user triggers a multi-turn operation (e.g., File Organization). The `WorkspaceOrganizeCapability` will first output a "Preview" and ask the user to confirm. 
- If the user simply replies "yes" or "go ahead", the **Intent Router** (`senpai/planner/selection.py`) needs to know *what* they are saying yes to.
- It uses `_recent_assistant_texts(history, limit=3)` to look backwards in the chat history. If it spots the `【整理プレビュー` marker in the recent history, it automatically routes the "yes" intent back into the LLMPlanner to execute the pending reorganization.
- Looking back multiple turns provides **fault tolerance**: if the user asks a side question in between, or if the Chat LLM briefly hallucinates an intermediate answer, the system still remembers the pending preview.

## 3. Tool Grounding (`ContextVars`)
A common failure mode in LLM agents is that a user says:
> *"Can you generate a proposal for that company we just talked about?"*

The standard Chat LLM knows what company it is, but the `generate_pptx` tool runs in isolation and doesn't have the chat history, so it generates a generic, hallucinated deck.

**How we solve this:**
1. Right before the Execution Engine dispatches parallel tools, `client.py` calls `set_conversation(convo)` (`senpai/tools/conversation.py`).
2. This drops a snapshot of the live conversation into a **`contextvars.ContextVar`**.
3. When the Execution Engine spawns new `threading.Thread` workers to run tools in parallel, it uses `contextvars.copy_context()` to ensure every worker thread safely inherits the conversation context.
4. The `ConversationCapability` reads this context, extracts the previously discussed companies/facts, and injects them into the new document's grounding bundle.

By using `ContextVar` instead of global variables, we guarantee that if 5 different users are talking to the server concurrently, their tools will never cross-contaminate each other's chat histories.

### 3a. Selecting *which* history to inject (relevance, not just recency)
`_conversation_grounding` (`senpai/tools/impl.py`) does not simply take the last N messages. Recency alone silently drops the entity in focus once a few unrelated turns intervene (a side question, extra tool calls) — which reintroduces the exact ungrounded-deck bug this grounding was built to prevent.

Instead it ranks by **relevance to the current request**:
- The most recent `_CONVO_RECENT_FLOOR` (3) snippets are always kept — the immediate context (the current request and the tool result that just landed).
- The remaining budget up to `_CONVO_MAX_SNIPPETS` (8) goes to the **older** snippets that best match the request, scored by token overlap with the prompt.
- Scoring is **script-agnostic** (`_relevance_tokens`): Latin/number words plus **CJK character bigrams**, so "村田印刷" shares the keys 村田/田印/印刷 across query and snippet. This deliberately avoids depending on the optional `janome` analyzer, whose whitespace fallback cannot segment Japanese.
- With no query signal at all, it degrades gracefully to pure recency (the original behavior).

### 3c. SessionFocus — the resolved entity (`senpai/tools/focus.py`)
Text grounding tells the doc author *what was said*; `SessionFocus` tells it *which record is in play*. It is **derived from the published conversation**, not a mutated object — the server is stateless per request and a per-turn `ContextVar` set on a worker thread doesn't survive to the next turn, so a live-mutated focus set when a CRM lookup resolved a customer would be gone by the next turn's document tool.

It is keyed off the **unambiguous IDs that real tool results emitted** (`D001` deal, `C13` customer), newest-first. An ID in a tool result means a tool *genuinely resolved* that entity, so focus is authoritative. It deliberately does **not** re-run fuzzy name matching — that is exactly what produced the wrong-company (松田 for a 村田 request) deck.

`_gather_grounding` now reads CRM in trust order: explicit customer arg → `SessionFocus` (deal in focus grounds on that specific deal) → fuzzy prompt match only as a last resort when the workspace didn't already pin the entity. This replaced the fragile `cust is None and not ws` guard and makes "that company we discussed" a lookup, not a re-inference.

### 3b. Boundary-aware truncation (`_truncate_on_boundary`)
Both the conversation grounding (4000-char budget) and each parallel tool result fed back to the model (`client.py`, 1500-char cap) are trimmed on a **natural boundary** — snippet break → paragraph → line → sentence → word — rather than a blind `text[:limit]`. A mid-string cut can drop the second half of a company name or a quote figure (`¥204,000`), handing the model half a fact; boundary trimming keeps facts intact and marks the elision with `…`.
