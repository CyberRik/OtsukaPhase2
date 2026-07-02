# Local Workspace Agent: E2E Architecture

The Local Workspace Agent handles the chatbot's interactions with the user's local filesystem (`E:\my_stuff`). It transforms the AI from a simple read-only knowledge bot into an active local assistant that can **search heavily-nested directories, synthesize new local documents, and autonomously organize loose files.**

This document details the end-to-end (E2E) pipeline of how the local agent safely orchestrates these operations.

---

## 1. Goal Routing & Planner Selection

When a user submits a prompt like *"Search my local files for the latest Yamato quote,"* *"Save these talking points to a note,"* or *"put w3.pdf under presentations,"* the request passes through the **Intent Router** (`senpai/api/server.py`):

1. **Routing**: `_is_planner_goal()` intercepts intents containing "create/generate", "save/note", or "organize/tidy" (including "put/move X into Y"). These are dispatched to the `_plan_stream` rather than the standard ReAct chat loop.
2. **Context-Aware Affirmation Memory**: The router keeps track of recent assistant responses (up to 3 turns back). If an "Organize Preview" was recently shown, a simple user affirmation like "go ahead" or "apply" will automatically re-route into the planner to execute the pending reorganization, even if the model hallucinated a turn in between.
3. **Capability Selection**: The `LLMPlanner` analyzes the goal and selects a static graph (DAG) of required capabilities. For local tasks, it typically selects `workspace`, `conversation`, and a terminal operation capability like `workspace_write` or `workspace_organize`.

---

## 2. Optimized File Discovery (The Sandbox)

Because the agent's root is `E:\my_stuff`—a massive parent directory that may contain heavy development folders—performing a standard recursive file search (`rglob("*")`) would freeze the server.

### In-Place Pruning
The `list_documents()` logic (`senpai/workspace/sandbox.py`) uses an optimized pruning directory walker (`os.walk`). It intercepts the directory tree traversal and immediately **skips** directories that match known ignore patterns (or start with a dot):
- `.git`
- `node_modules`
- `.venv`, `venv`
- `.next`, `__pycache__`, `dist`
- `generated` (prevents self-feeding on previously generated output)

By pruning these *before* descending into them, the scanner is practically instantaneous and strictly localizes the search to actual documents and source files.

### Safety & Sandboxing
The workspace agent relies strictly on `safe_path(candidate)`. Every resolved path (including symlinks) must stay inside the `WORKSPACE_ROOT`. Escaping via `../../` throws a `SandboxError`. The agent cannot touch any file outside this root.

---

## 3. Parallel Task Orchestration

The selected capability graph is executed by the **Execution Engine** (`ExecutionEngine.run`). 

### Gather: Document Synthesis (`WorkspaceCapability`)
If the task requires reading:
1. The engine spins up `WorkspaceCapability` in a worker thread.
2. It retrieves the file paths from the sandbox and runs parallel extraction tasks on the candidates to find relevant text.
3. The extracted text is packaged into an immutable `Evidence` fragment, bundled alongside any CRM or Web search context.

### Write: Note Generation (`WorkspaceWriteCapability`)
1. The terminal capability consumes the `EvidenceBundle`.
2. It passes the gathered text and the user's goal to the LLM to author a localized, markdown-formatted note.
3. It determines a filename (either extracted from the goal, or slugified under `notes/`) and invokes `edit_workspace_document(confirm=True)`.

### Tidy: File Organization (`WorkspaceOrganizeCapability`)
The agent can actively clean the workspace by organizing loose root-level documents into topic folders (e.g., `quotes/`, `proposals/`, `meeting-notes/`, `reports/`).

1. **Classification**: Root-level files are mapped to folders using an LLM JSON classifier (with a deterministic keyword-based fallback). Files already inside subfolders are deliberately left alone to avoid churning established structures.
2. **Two-Turn Preview**: Destructive operations use a safety confirm. The initial pass defaults to `op="plan"`, emitting a read-only list of proposed moves (e.g., `  estimate.pdf → quotes/estimate.pdf`).
3. **Execution**: If the user affirms ("yes", "apply"), the chat tracks the context and reruns the capability with `op="apply"`. The sandbox primitive `move_within` executes the changes, ensuring zero overwrites and preventing data loss.

---

## Summary
The local workspace agent combines **intelligent routing**, **optimized and sandboxed file discovery**, and **parallel capability orchestration** to securely read, write, and manage thousands of local files in near real-time without compromising system stability.
