# Admin Portal Visualization Architecture (Detailed Guide)

This document provides a comprehensive, code-level explanation of the visualization architecture introduced in commit `3761dfcc7e4554df2c7b454da14e8aab7e772cb7`. It covers the migration, the exact data flows, how the frontend and backend interact, and detailed instructions for extending or modifying the visualizations.

---

## 1. The Migration: Before vs. After

### The Old Architecture (Removed)
Previously, the visualization was a detached, demo-only toolset:
- **`senpai/api/visualization_server.py`**: A separate FastAPI server that used **WebSockets** to stream events.
- **`senpai/graph/query_instrumented.py`**: A duplicated, heavily instrumented version of the query logic just to emit visualization events.
- **`senpai/graph/visualization.py`**: A centralized event Hub for broadcasting.
- **`tools/graph_viz_dashboard.html`**: A massive, single HTML file with embedded JavaScript and D3/Canvas code to render the graph.

**Why it was removed:** It was disconnected from the main application, required running a separate server script, used fragile WebSockets, and duplicated core query logic.

### The New Architecture (Integrated)
The visualization is now a first-class feature of the main Admin Portal.
- **Main FastAPI Server (`senpai/api/server.py`)**: Endpoints are natively integrated. WebSockets were replaced by **Server-Sent Events (SSE)** for simpler, one-way streaming.
- **Unified Query Logic**: The backend no longer maintains a separate `query_instrumented.py`. It runs the real graph query and emits the trace simultaneously.
- **Next.js Frontend (`web/app/admin/visualization`)**: The graph is rendered inside the React application using `react-force-graph-2d`.

---

## 2. Backend Implementation (FastAPI)

The backend exposes three core endpoints in `senpai/api/server.py`:

### A. Static Network Graph (`GET /api/admin/graph`)
Returns the complete NetworkX graph serialized for the frontend.
```python
@app.get("/api/admin/graph")
def admin_graph(kind: str | None = None):
    from senpai.graph import build as _build
    G = _build.graph()  # Fetches the real NetworkX graph
    
    # ... filters out nodes if `kind` is provided ...
    
    nodes = [{"id": n, "label": _node_label(n, d), "kind": d.get("kind", "unknown"),
              "degree": G.degree(n), **d} for n, d in G.nodes(data=True)]
    links = [{"source": u, "target": v, "rel": d.get("rel", "")}
             for u, v, d in G.edges(data=True)]
    return {"nodes": nodes, "links": links, "stats": _build.stats()}
```

### B. Community Map (`GET /api/admin/communities`)
Returns the pre-calculated communities for the heatmap visualization.
```python
@app.get("/api/admin/communities")
def admin_communities():
    from senpai.graph import communities as _comm
    return {"communities": [dict(r) for r in _comm.load_reports()]}
```

### C. Live Graph-RAG Traversal (`POST /api/admin/graph-rag/run`)
This is the core engine for the "Live" and "Versus" pages. It uses FastAPI's `StreamingResponse` to send Server-Sent Events (SSE) formatted as `data: {...}\n\n`.

**How `_run_graph_rag_stream(query)` works:**
1. **Graph Retrieval:** It calls `_comm.select(query)` and `_gq.reps_who_win()`.
2. **Event Streaming:** As it pulls communities and reps, it yields `node_visited` and `edge_traversed` events.
   ```python
   yield 'data: {"type": "node_visited", "kind": "community", "label": "...", "n_deals": 5}\n\n'
   ```
3. **Trace Draining:** It pulls the raw semantic retrieval trace (`_trace.drain()`) and yields it as `retrieved` events.
4. **Traditional Retrieval:** It performs a standard vector search (`_sem.semantic_search`) on the exact same query.
5. **Comparison:** It measures the latency, token counts, and chunk sizes of both approaches, yielding a final `comparison` event containing a scorecard.

---

## 3. Frontend Implementation (Next.js & React)

### A. The API Client (`web/lib/api.ts`)
The `graphRagStream` function connects to the SSE endpoint and parses the stream using a custom `readSSE` buffer loop.
```typescript
export async function graphRagStream(
  query: string,
  onEvent: (e: GraphRagEvent) => void
) {
  const res = await fetch("/api/admin/graph-rag/run", { method: "POST", ... });
  await readSSE(res, (obj) => onEvent(obj as GraphRagEvent));
}
```

### B. The React Force Graph (`web/components/admin/force-graph.tsx`)
Because `react-force-graph-2d` relies on the HTML5 Canvas API and the browser `window` object, it **must** be imported dynamically with Server-Side Rendering (SSR) disabled:
```typescript
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });
```
**Customizations in `ForceGraphView`:**
- **Sizing:** `nodeVal` determines the circle size. It defaults to `Math.max(1, node.degree)`.
- **Colors:** Determines color based on the node's `kind` (e.g., green for rep, blue for deal). If a `highlightIds` Set is provided (used during Live Traversal), non-highlighted nodes fade to `rgba(120,130,160,0.25)`.
- **Labels:** Uses the `nodeCanvasObject` hook to draw text on the canvas. To prevent visual clutter, labels are *only* drawn if the node has a degree > 12 or if it's currently highlighted.

### C. Live Traversal Page (`web/app/admin/visualization/live/page.tsx`)
1. Fetches the static graph via `useFetched(api.adminGraph)`.
2. When the user clicks "Run", it triggers `graphRagStream()`.
3. As SSE events arrive:
   - `node_visited` / `edge_traversed`: The node IDs are added to a `highlight` Set in React state.
   - The `ForceGraphView` receives this `highlight` Set as a prop and instantly dims the rest of the graph, visually "walking" the path.
   - `retrieved`: Raw JSON chunks are appended to a side panel.
   - `comparison`: The `ComparisonScorecard` component appears, rendering the latency/chunk metrics.

### D. Community Map (`web/app/admin/visualization/communities/page.tsx`)
A completely custom layout (no force graph). It maps `categories` into rows, and `leaves` into tiles.
- **Tile Size:** Calculated dynamically: `40 + (leaf.n_deals / maxDeals) * 60`.
- **Tile Color:** Uses `winColor(leaf.win_rate)` to generate a heat-map gradient (red for low win rate, green for high).

---

## 4. How to Make Changes

### Scenario 1: Changing Graph Visuals (Colors, Sizes, Labels)
To change how the Network Graph looks, edit `web/components/admin/force-graph.tsx`.

- **Change Node Size Logic:** 
  Find `nodeVal={(n: FGNode) => Math.max(1, (n.val ?? n.degree ?? 1))}` and modify the formula.
- **Change Label Logic:** 
  Find `nodeCanvasObject`. You can change the font size `ctx.font = \`\${11 / scale}px Inter\`` or the visibility condition `const show = (node.degree ?? 0) > 12`.
- **Change Node Colors:** 
  Node colors are defined by the `KIND_COLOR` constant imported from `web/components/admin/kit.tsx`. Edit that file to change the hex codes for `rep`, `deal`, `product`, etc.

### Scenario 2: Adding New Data to the Graph
If you want to visualize a new entity (e.g., "Region"):
1. **Backend (`senpai/api/server.py`)**: Ensure `admin_graph()` includes your new property when parsing `G.nodes(data=True)`.
2. **Frontend (`web/app/admin/visualization/network/page.tsx`)**: In the `NetworkPage`, add `"region"` to the `KINDS` array so it appears in the filter buttons. Add logic to the Selected Node detail card to display `selected.region`.

### Scenario 3: Modifying the Live Graph-RAG Traversal Trace
If you want the traversal animation to highlight a new step (e.g., a specific vector database lookup):
1. **Backend (`senpai/api/server.py`)**: Inside `_run_graph_rag_stream()`, `yield` a new event:
   ```python
   yield 'data: {"type": "db_lookup", "table": "products", "latency_ms": 45}\n\n'
   ```
2. **Frontend (`web/app/admin/visualization/live/page.tsx`)**: 
   Inside the `graphRagStream` callback, catch the new event type:
   ```typescript
   if (e.type === "db_lookup") {
     setVisits((v) => [...v, { kind: "db", label: `Looked up ${e.table}`, detail: `${e.latency_ms}ms` }]);
   }
   ```

### Scenario 4: Editing the Comparison Scorecard Metrics
If you want to track a new metric (e.g., "Cost"):
1. **Backend (`senpai/api/server.py`)**: In `_run_graph_rag_stream()`, add `"cost": 0.05` to the `graph` and `traditional` dictionaries inside the final `comparison` event.
2. **Frontend Types (`web/lib/admin-types.ts` or wherever defined)**: Add `cost: number` to the `ComparisonSide` interface.
3. **Frontend Component (`web/components/admin/comparison.tsx`)**: Render the new row inside `ComparisonScorecard`:
   ```tsx
   <Metric label="Cost" graph={graph.cost} trad={traditional.cost} unit="$" graphBetterWhenLower />
   ```