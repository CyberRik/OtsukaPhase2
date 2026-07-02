# Multi-Agent Crew Execution

The multi-agent crew execution (`/crew`) is a deterministic, parallelized analysis framework where a team of role-specialized agents investigates a single deal together. This replaces the single-model generative approach with a structured, multi-perspective synthesis based purely on actual internal data, eliminating hallucinations.

This document traces the technical evolution and exact implementation of the Crew execution model.

---

## 1. The Crew Roles & Execution Spine

The system employs three specialized agents, each strictly scoped by prompt and capability:

1. **🔍 Researcher (リサーチャー)**: Gathers facts without inference. It compiles the deal snapshot, comparable won deals, related daily-report risk signals, and the IT environment.
2. **🩺 Coach (コーチ)**: Focuses purely on deal health. Reads the deterministic risk band and specific signals, pinpointing areas of caution for the rep.
3. **♟️ Strategist (ストラテジスト)**: The synthesizer. Depends on both the Researcher's and Coach's output to formulate an actionable plan (talking points, objection handling, next moves).

### Concurrency and Streaming (`senpai/agent/crew.py`)
The orchestrator avoids sequence bottlenecks by running independent fact-gatherers in parallel. 
- **Threading**: The `Researcher` and `Coach` run on independent `threading.Thread` workers (`_worker`).
- **UI Streaming**: As they run, they push lifecycle events (`running`, `agent_tool`, `done`, `error`) into a shared `queue.Queue`. The frontend displays one distinct lane per agent.
- **Barrier Synchronization**: `_drain_parallel` pulls events from the queue until exactly `n_workers` have emitted their `_worker_done` signal. Once the queue drains, the `Strategist` begins synthesis based on the results dictionary populated by the threads.

---

## 2. Capability DAGs & Orchestration Upgrade

Initially, fact-gathering inside each agent was a manual sequence of function calls. To align with the system's larger architectural upgrade, the crew's data gathering was migrated to the **Orchestration Execution Engine** (`senpai.orchestration.ExecutionEngine`).

### Execution Plans (`senpai/agent/plan.py`)
Instead of inline code, each agent is assigned a fixed `ExecutionPlan` (a Directed Acyclic Graph of capabilities) containing tasks that represent the tools they need:
- **`researcher_plan`**: Runs four parallel tasks: `snapshot` (query_spr), `comparables` (find_similar_deals), `notes` (search_notes), and `env` (lookup_customer_environment).
- **`coach_plan`**: Runs a single task: `health` (score_deal_health).
- **`rep_analyst_plan`** (for Manager Fan-out): Runs `pipeline` (team_pipeline_overview) and `at_risk` (list_at_risk_deals).

These tasks represent exact 1:1 mappings of the old tools but execute concurrently on the orchestration engine's worker pool.

### The Gather Adapter (`senpai/agent/gather.py`)
Because the frontend UI expects legacy `agent_tool` events to draw the timeline, `run_agent_gather` acts as an adapter. 
It runs the agent's `ExecutionPlan` via `ExecutionEngine(_REGISTRY).run(plan, adapter)`. The `adapter` intercepts the engine's generic `TASK_STARTED` events and translates them back into `agent_tool` events containing the expected `name` and `summary`.

**Resilience**: The Execution Engine isolates failures. If a `web` or `notes` query times out, that task's status degrades to an empty string `""` for its slot. The gathering process never raises fatal exceptions, ensuring the `Strategist` always receives a bundle (even if partially empty) to synthesize.

---

## 3. Manager Fan-Out: Expanding the DAG

The same architecture powers the manager `/crew` invocation (team analysis).
Instead of analyzing a single deal, the `run_team` function dynamically fans out the threads:
1. **Risk Ranking**: `_rep_roster` computes the top 5 reps by highest risk exposure.
2. **Analyst Threads**: It spawns one `_rep_analyst` thread per rep in parallel. Each analyst runs its `rep_analyst_plan` through the Execution Engine and generates a coaching card.
3. **Synthesis**: The `Team Lead` agent waits for all analyst threads to complete, synthesizes the coaching cards, and outputs a prioritized action list (most critical deals, coaching focus).

---

## 4. Resolution and Target Handling

When the user invokes `/crew [target]`, `resolve_crew_target` enforces the system's strict resolution trust model:
- **Explicit Target**: Matches an explicit deal ID (`D001`) or unique customer to their *Key Deal* (the worst-health OPEN deal).
- **Ambiguity**: If the input is vague (e.g., "fujimoto"), it does not guess. It returns an `ambiguous` status and the matching `stem`, prompting the frontend to render the deterministic customer-picker.

*This guarantees that every crew execution is anchored to a proven ID in the store, avoiding the risk of a multi-agent hallucination over wrong data.*
