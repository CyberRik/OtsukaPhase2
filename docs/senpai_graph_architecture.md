# In-Depth Architecture: Senpai Graph Module (`@senpai/graph/`)

This document provides a comprehensive, ground-up explanation of the `@senpai/graph/` module. It details the internal data structures, algorithms, and exact implementation strategies used to construct the SPR Knowledge Graph and power "Segment Intelligence" (GraphRAG).

The core philosophy of this module is **Deterministic-First AI Engineering**. It minimizes live LLM usage to guarantee speed, reduce costs, and structurally eliminate hallucinations by enforcing mathematical grounding on all AI-generated text.

---

## 1. Graph Construction: `build.py`
This module is responsible for translating flat, relational data from the database (`senpai.data.store`) into an in-memory, highly connected network graph.

### Data Structure: `networkx.MultiDiGraph`
The system uses `MultiDiGraph` from the `networkx` library. This allows for directed edges (A points to B) and multiple edges between the same two nodes (e.g., if a rep owned a deal, and also reviewed it).

### Node and Edge Schema
The `graph()` function loops through all core entities and builds the following topology:

*   **Reps (`rep`)**: Attributes include `name`, `role`, `department`, `specialty_tags`.
    *   *Edges*: `-OWNS->` Deal
*   **Customers (`customer`)**: Attributes include `name`, `industry`, `size`.
    *   *Edges*: `-IN_INDUSTRY->` Industry Node
*   **Products (`product`)**: Attributes include `name`, `major`, `mid`.
*   **Deals (`deal`)**: Highly **denormalized**. To make graph queries incredibly fast, Deal nodes don't just store an ID. They duplicate critical filterable data: `name`, `rank`, `outcome` (won/lost/open), `amount`, `category`, `industry`, `rep`, `products`, and `acttypes`.
    *   *Edges*: 
        *   `-FOR->` Customer
        *   `-CONCERNS->` Product
        *   `-IN_CATEGORY->` Category Node
        *   `-HAD->` ActivityType Node

### Implementation Details
*   **Performance via Caching**: The `graph()` function is decorated with `@lru_cache(maxsize=1)`. The application only incurs the cost of building the graph once per session. Subsequent calls return the memory reference instantly.
*   **Grouping Nodes**: Instead of just linking deals to raw strings, the graph creates explicit "grouping nodes" like `industry:Manufacturing` or `acttype:site_survey`. This makes algorithms like "shortest path" naturally route through shared attributes.

---

## 2. Multi-Hop Relational Queries: `query.py`
This file exposes deterministic Python functions to traverse the graph built in `build.py`. Because the graph is loaded in memory, these multi-hop questions are answered in milliseconds without ever querying an LLM.

### A. `reps_who_win(category, industry, after_activity_type)`
Answers: *"Which reps are actually successful at selling X to Y?"*
1.  **Traversal**: It iterates over all `deal` nodes using `deal_nodes(G)`.
2.  **Filtering**: It immediately skips `open` deals (because they have no win/loss signal). It applies filters for `category`, `industry`, and `acttypes` directly against the denormalized deal attributes.
3.  **Aggregation**: It builds a dictionary tracking `won` and `closed` (total) counts per rep, storing example deal IDs as evidence.
4.  **Ranking**: It calculates the `win_rate` (`won / closed`) and sorts reps in descending order, requiring a minimum number of deals (`min_deals`) to qualify.

### B. `account_graph(customer)`
Answers: *"Give me the entire context of what is happening at this customer."*
1.  **Resolution**: Resolves the customer name/ID to a specific `customer_id`.
2.  **In-Edges**: Looks at `G.in_edges(cid)` to find all nodes pointing to the customer with a `FOR` relationship (which reveals all Deals).
3.  **Expansion**: For every deal found, it inspects the deal's attributes to compile a unique `set()` of all Reps and Products that have ever touched this account.

### C. `connections(entity_a, entity_b)`
Answers: *"How is Product X connected to Customer Y?"*
1.  **Undirected Conversion**: It temporarily creates an undirected view of the graph `G.to_undirected(as_view=True)`.
2.  **Dijkstra's Algorithm**: Uses `nx.shortest_path(UG, ua, ub)` to find the shortest hop distance between the two entities.
3.  **Path Explanation**: Returns the sequence of nodes bridging the gap (e.g., Product X -> Deal 123 -> Rep John -> Deal 456 -> Customer Y).

### D. `similar_by_graph(deal_id)`
Answers: *"Find deals structurally similar to this one."*
Instead of using vector embeddings for semantic similarity, it uses a graph heuristic scoring system:
*   Iterates over all other deals.
*   Adds `+1` point if they share the same **Rep**.
*   Adds `+2` points for *each* shared **Product** (indicating high overlap).
*   Adds `+1` point if they share the same **Category**.
*   Adds `+1` point if they share the same **Industry**.
*   Sorts by score and returns the top matches.

---

## 3. The GraphRAG Engine: `communities.py`
This file implements "Segment Intelligence", which groups deals into thematic communities and calculates their health. It is purely deterministic (no AI).

### Hierarchy & Partitioning (`build_reports`)
1.  **Grouping**: Deals are grouped into a dictionary by a tuple of `(Category, Industry)`. These are the "Leaves".
2.  **Rollups**: Thin leaves (e.g., a specific Category/Industry pairing with fewer than `config.SEGMENT_MIN_DEALS` closed deals) are discarded. Their data naturally rolls up to the broader "Category" level report to maintain statistical significance.

### Statistical Aggregation (`segment_stats`)
For a given list of deals in a segment, this function runs a heavy, deterministic calculation:
1.  **Scoring**: It runs `score_deal()` and `deal_flags()` (from `senpai.health`) on every deal to assess stall risks, missing decision-makers, etc.
2.  **Tallying**: It uses Python's `collections.Counter` to track `sig_counter` (why lost deals were lost) and `flag_counter` (general risks across all deals).
3.  **Principle Mapping**: It takes the top 2 failure signals (e.g., `stall_language`) and maps them to human-authored coaching principles (`THEME_PRINCIPLES`).

### The Grounding Gate (Hallucination Prevention)
This is the most critical safety mechanism in the module. It ensures an LLM can *never* hallucinate a statistic.
1.  **`allowed_numbers(report)`**: Scrapes the calculated stats and builds a mathematical whitelist of allowed strings. For example, if there are 15 deals, a 40% win rate, and 3 missing DMs, the set is `{'15', '40', '3'}`. It also extracts digits from Principle IDs (e.g., `P003` -> `003`).
2.  **`ungrounded_numbers(text, report)`**: Uses the regex `_NUM = re.compile(r"\d+")` to extract every single number from an LLM-generated string. If *any* number in the text is not in the `allowed_numbers` set, it flags the text as hallucinated.

---

## 4. Offline LLM Compilation: `build_communities.py`
This script uses an LLM to turn the hard statistics from `communities.py` into fluid Japanese prose. It is designed to be run **offline** (e.g., cron job or build pipeline), meaning the user never waits for an LLM at runtime.

### The Prompt (`_SYS`)
The system prompt strictly instructs the LLM to act as a data translator:
> "You are an analyst for sales managers. Summarize the trends of this segment in 2-3 Japanese sentences based ONLY on the provided JSON stats. Rules: (1) Do not write numbers/rates not in the stats. (2) Do not write individual deal IDs. (3) Do not add guesses or new advice."

### The Verification Loop (`_llm_narrative`)
1.  **Inference**: It calls `simple_complete()` with `temperature=0.4` (low creativity to encourage factual adherence).
2.  **Gate Check**: It passes the generated text immediately to `ungrounded_numbers(text, report)`.
3.  **Fallback Mechanism**:
    *   If the model hallucinates an ungrounded number, raises an API exception, or returns empty text, the system throws the text away.
    *   It falls back to a deterministic, templated string generated by `_narrative()` in `communities.py` (e.g., *"【Servers×Manufacturing】 10 deals. Win rate 40%. Top failure: Stalled (3 cases)."*).

### State Persistence
The script writes the final array of reports to `communities.json` and tallies a `communities.manifest.json` (tracking how many reports used LLMs vs. templated fallbacks). At runtime, `communities.load_reports()` just reads this static JSON file from disk, resulting in instantaneous, pre-verified GraphRAG reports.