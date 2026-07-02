// Typed client for the Senpai FastAPI bridge. Every call falls back to the
// committed fixtures when the API is unreachable, so the demo never shows a
// broken screen â€” it shows real-shaped data and a small "offline" hint.

import {
  COACH_EXAMPLES,
  COACH_FALLBACK,
  COACHING_FALLBACK,
  DASHBOARD_FALLBACK,
  GROWTH_FALLBACK,
  ITEMS_FALLBACK,
  PRINCIPLES_FALLBACK,
  REP_PROFILES_FALLBACK,
  SOURCES_FALLBACK,
} from "./fixtures";
import type {
  AccountSummary,
  AccountStrategy,
  CoachExample,
  CoachingWorkspace,
  CoachResponse,
  DashboardData,
  DealDetail,
  GrowthResponse,
  KnowledgeItem,
  Principle,
  RepProfile,
  RepProfileRow,
  RepProgress,
  AddPrincipleRequest,
  CoachingThread,
  ExtractResult,
  GeneratedDocument,
  IngestResult,
  SaveActivityRequest,
  SaveActivityResult,
  SimilarCase,
  Source,
} from "./types";
import type { ArtifactKind, EntityRef } from "./artifacts";
import type {
  AdminOverview,
  AdminRep,
  ManagerRef,
  AdminOrg,
  AdminActivityEvent,
  AdminAccount,
  AdminPipelineHealth,
  AdminSystemStatus,
  AdminUsage,
  AdminGraph,
  Community,
  GraphRagEvent,
} from "./admin-types";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

export interface Fetched<T> {
  data: T;
  live: boolean;
}

// Absolute URL for a generated document's download (bridge-relative path -> BASE).
export function documentUrl(downloadUrl: string): string {
  return downloadUrl.startsWith("http") ? downloadUrl : `${BASE}${downloadUrl}`;
}

async function get<T>(path: string, fallback: T): Promise<Fetched<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status}`);
    return { data: (await res.json()) as T, live: true };
  } catch {
    return { data: fallback, live: false };
  }
}

async function post<T>(path: string, body: unknown, fallback: T): Promise<Fetched<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return { data: (await res.json()) as T, live: true };
  } catch {
    return { data: fallback, live: false };
  }
}

// --- auth --------------------------------------------------------------------
// Signup/login hit the bridge directly. Unlike the read endpoints there's no
// fixture fallback — auth must be real — so failures surface as { ok:false }.
export interface AuthResult {
  ok: boolean;
  token?: string;
  username?: string;
  role?: "junior" | "manager";
  employee_id?: string | null;
  error?: string;
}

async function authPost(path: string, body: unknown): Promise<AuthResult> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (!res.ok) {
      return { ok: false, error: (data.detail as string) ?? `http_${res.status}` };
    }
    return {
      ok: true,
      token: data.token as string,
      username: data.username as string,
      role: data.role as "junior" | "manager",
      employee_id: (data.employee_id as string | null) ?? null,
    };
  } catch {
    return { ok: false, error: "network" };
  }
}

export const api = {
  // The manager pool for the junior signup picker ("who's your manager?").
  managerReps: () =>
    get<{ managers: { employee_id: string; name: string; role: string; department: string; division: string }[] }>(
      "/api/reps/managers",
      { managers: [] },
    ),
  // Register a new junior: creates a fresh rep assigned to `managerId`.
  signup: (username: string, password: string, name: string, managerId: string) =>
    authPost("/api/auth/signup", { username, password, name, manager_id: managerId }),
  login: (username: string, password: string) =>
    authPost("/api/auth/login", { username, password }),
  // `manager` (an employee_id) scopes the dashboard to that manager's coachees.
  dashboard: (rep?: string, manager?: string) => {
    const qs = new URLSearchParams();
    if (rep && rep !== "(all)") qs.set("rep", rep);
    if (manager) qs.set("manager", manager);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return get<DashboardData>(`/api/dashboard${suffix}`, DASHBOARD_FALLBACK);
  },
  deal: (id: string) => get<DealDetail | null>(`/api/deals/${id}`, null),
  coach: (note: string, deal_id?: string, narrate = false) =>
    post<CoachResponse>("/api/coach/review", { note, deal_id, narrate }, COACH_FALLBACK),
  coachExamples: () =>
    get<{ examples: CoachExample[] }>("/api/coach/examples", { examples: COACH_EXAMPLES }),
  similarCases: (note: string, deal_id?: string) =>
    post<{ cases: SimilarCase[] }>("/api/coach/similar-cases", { note, deal_id }, { cases: [] }),
  principles: () =>
    get<{ principles: Principle[]; counts: Record<string, number> }>(
      "/api/knowledge/principles",
      { principles: PRINCIPLES_FALLBACK, counts: { total: 11, approved: 4, pending: 7, two_source: 4 } },
    ),
  items: () =>
    get<{ items: KnowledgeItem[]; counts: Record<string, number> }>(
      "/api/knowledge/items",
      { items: ITEMS_FALLBACK, counts: { total: 4, approved: 4, pending: 0 } },
    ),
  sources: () =>
    get<{ sources: Source[] }>("/api/knowledge/sources", { sources: SOURCES_FALLBACK }),
  // Knowledge authoring (manager). Mutations: when offline, `live` is false and
  // `item` is null â€” the UI surfaces that rather than pretending it succeeded.
  knowledgeGenerate: (principleId: string, useLlm = false) =>
    post<{ item: KnowledgeItem | null }>(
      "/api/knowledge/generate",
      { principle_id: principleId, use_llm: useLlm },
      { item: null },
    ),
  // Manager contributes tacit knowledge â†’ a candidate principle.
  addPrinciple: (body: AddPrincipleRequest) =>
    post<{ principle: Principle | null }>(
      "/api/knowledge/principles",
      body,
      { principle: null },
    ),
  knowledgeReview: (
    itemId: string,
    action: "approve" | "request_edit" | "reject",
    notes = "",
  ) =>
    post<{ item: KnowledgeItem | null }>(
      `/api/knowledge/items/${encodeURIComponent(itemId)}/review`,
      { action, notes },
      { item: null },
    ),
  growth: (rep?: string) =>
    get<GrowthResponse>(`/api/growth${rep ? `?rep=${encodeURIComponent(rep)}` : ""}`, GROWTH_FALLBACK),
  // `manager` (an employee_id) scopes to that manager's coachees; omit for all.
  coaching: (manager?: string) =>
    get<CoachingWorkspace>(
      `/api/coaching${manager ? `?manager=${encodeURIComponent(manager)}` : ""}`,
      COACHING_FALLBACK,
    ),
  // Per-rep 1:1 coaching. Rollup has a fixture fallback; the drill-downs return
  // null/[] offline (the UI hides those panels when data is absent).
  repProfiles: (manager?: string) =>
    get<{ reps: RepProfileRow[] }>(
      `/api/coach/rep-profiles${manager ? `?manager=${encodeURIComponent(manager)}` : ""}`,
      { reps: REP_PROFILES_FALLBACK },
    ),
  // "My team" roster for a manager — includes zero-deal (newly-assigned) reps.
  coachTeam: (manager?: string) =>
    get<{ reps: { employee_id: string; name: string; role: string; open_deals: number }[] }>(
      `/api/coach/team${manager ? `?manager=${encodeURIComponent(manager)}` : ""}`,
      { reps: [] },
    ),
  repProfile: (employeeId: string) =>
    get<RepProfile | null>(`/api/coach/rep-profile/${encodeURIComponent(employeeId)}`, null),
  repProgress: (employeeId: string, windows = 4) =>
    get<RepProgress | null>(
      `/api/coach/rep-progress/${encodeURIComponent(employeeId)}?windows=${windows}`,
      null
    ),
  coachThreads: (opts: { repId?: string; dealId?: string } = {}) => {
    const qs = new URLSearchParams();
    if (opts.repId) qs.set("rep_id", opts.repId);
    if (opts.dealId) qs.set("deal_id", opts.dealId);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return get<{ threads: CoachingThread[] }>(`/api/coach/threads${suffix}`, { threads: [] });
  },
  account: (customerId: string) =>
    get<AccountSummary | null>(`/api/account/${encodeURIComponent(customerId)}`, null),
  resolveCustomer: (q: string) =>
    get<{ status: "resolved" | "ambiguous" | "not_found"; query: string; customer?: any; candidates?: ResolveCandidate[] }>(
      `/api/customers/resolve?q=${encodeURIComponent(q)}`,
      { status: "not_found", query: q }
    ),
  smartResolveCustomer: (query: string, lang = "ja") =>
    post<{
      status: "resolved" | "ambiguous" | "not_found";
      query: string;
      customer?: any;
      candidates?: { customer_id: string; name: string }[];
      suggested_id?: string | null;
    }>(
      "/api/customers/smart-resolve",
      { query, lang },
      { status: "not_found", query, customer: null, candidates: [] }
    ),
  // Attachment â†’ plain text for chat context (no structured extraction).
  // Multipart upload; returns null when the API is down or extraction is empty.
  extract: async (
    input: { audio?: File; image?: File; text?: string },
  ): Promise<{ data: ExtractResult | null; live: boolean }> => {
    const fd = new FormData();
    if (input.audio) fd.append("audio", input.audio);
    if (input.image) fd.append("image", input.image);
    if (input.text) fd.append("text", input.text);
    try {
      const res = await fetch(`${BASE}/api/extract`, { method: "POST", body: fd });
      if (!res.ok) return { data: null, live: false };
      return { data: (await res.json()) as ExtractResult, live: true };
    } catch {
      return { data: null, live: false };
    }
  },
  // Multimodal capture â†’ structured draft. Multipart upload, so it bypasses the
  // JSON `post` helper. Returns { data:null, live:false } when the API is down.
  ingest: async (
    input: { audio?: File; image?: File; text?: string },
  ): Promise<{ data: IngestResult | null; live: boolean }> => {
    const fd = new FormData();
    if (input.audio) fd.append("audio", input.audio);
    if (input.image) fd.append("image", input.image);
    if (input.text) fd.append("text", input.text);
    try {
      const res = await fetch(`${BASE}/api/ingest`, { method: "POST", body: fd });
      if (!res.ok) return { data: null, live: false };
      return { data: (await res.json()) as IngestResult, live: true };
    } catch {
      return { data: null, live: false };
    }
  },
  // Persist a reviewed daily-report draft as a real sales_activities row.
  saveActivity: (body: SaveActivityRequest) =>
    post<SaveActivityResult>("/api/ingest/save", body, { saved: false, activity: null }),

  // --- admin portal (internal-only; see senpai/api/server.py) ----------------
  adminOverview: () =>
    get<AdminOverview>("/api/admin/overview", {
      reps: 0, managers: 0, juniors: 0, accounts: 0, deals: 0, open_deals: 0,
      communities: 0, knowledge_pending: 0, tokens_total: 0, llm_calls: 0,
    }),
  adminReps: () =>
    get<{ reps: AdminRep[]; managers: ManagerRef[] }>("/api/admin/reps", { reps: [], managers: [] }),
  adminOrg: () =>
    get<AdminOrg>("/api/admin/org", { groups: [], unassigned: [], manager_pool: [] }),
  adminActivity: () =>
    get<{ events: AdminActivityEvent[] }>("/api/admin/activity", { events: [] }),
  adminAccounts: () =>
    get<{ accounts: AdminAccount[] }>("/api/admin/accounts", { accounts: [] }),
  adminPipelineHealth: () =>
    get<AdminPipelineHealth>("/api/admin/pipeline-health", {
      totals: { n_deals: 0, n_won: 0, n_lost: 0, n_open: 0 },
      failure_signals: [], lowest_win_segments: [],
    }),
  adminSystemStatus: () =>
    get<AdminSystemStatus>("/api/admin/system-status", {
      use_llm: false, today: "", retrieval_mode: "unknown",
      endpoints: { primary: { base_url: "", model: "" }, fallback: { base_url: "", model: "" } },
      flags: {}, data: { reps: 0, deals: 0, overlays: [] },
    }),
  adminUsage: () =>
    get<AdminUsage>("/api/admin/usage", {
      totals: { calls: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated_calls: 0, est_cost: 0 },
      cost_per_1k: 0, by_day: [], by_model: [], by_label: [], recent: [],
    }),
  adminGraph: (kind?: string) =>
    get<AdminGraph>(`/api/admin/graph${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`, { nodes: [], links: [], stats: {} }),
  adminCommunities: () =>
    get<{ communities: Community[] }>("/api/admin/communities", { communities: [] }),
  adminReassign: (employeeId: string, managerId: string) =>
    post<{ rep: AdminRep | null }>(`/api/admin/reps/${employeeId}/reassign`, { manager_id: managerId }, { rep: null }),
};

// --- Streaming senior commentary (SSE from the vLLM-backed bridge) ----------
export type NarrateEvent =
  | { type: "start"; model?: string; endpoint?: string }
  | { type: "artifact_meta"; kind: ArtifactKind; entity_ref?: EntityRef }
  | { type: "thinking"; chars: number }
  | { type: "context"; grounded: boolean; customer?: string | null; deal_id?: string | null; cached?: boolean; candidates?: ResolveCandidate[] }
  | { type: "awaiting_choice" }
  | { type: "delta"; text: string }
  | { type: "done"; model?: string }
  | { type: "fallback" }
  | { type: "unavailable"; reason?: string }
  | { type: "error"; reason?: string };

/**
 * Stream the senior commentary token-by-token. Resolves when the stream ends.
 * Any transport failure surfaces as an `error` event (never throws), so the
 * caller can fall back to the deterministic Review Coach card.
 */
export async function narrateStream(
  note: string,
  deal_id: string | undefined,
  onEvent: (e: NarrateEvent) => void,
  opts?: { lang?: "ja" | "en"; signal?: AbortSignal; conversationId?: string },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/coach/narrate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note, deal_id, narrate: true, lang: opts?.lang ?? "ja",
                             conversation_id: opts?.conversationId }),
      cache: "no-store",
      signal: opts?.signal,
    });
  } catch {
    console.error(`network error`); onEvent({ type: "error", reason: "network" });
    return;
  }
  if (!res.ok || !res.body) {
    console.error(`http error: ${res.status}`); onEvent({ type: "error", reason: `http_${res.status}` });
    return;
  }

  await readSSE(res, (obj) => onEvent(obj as NarrateEvent), () =>
    onEvent({ type: "error", reason: "stream" }),
  );
}

// --- Tool-calling chat assistant (junior / manager) -------------------------
// Streams one assistant turn from /api/chat. The model autonomously calls the
// deterministic sales tools (and web_search); each executed tool arrives as a
// `tool` event before the final `answer`.
export type ChatRole = "junior" | "manager" | "research";

// A customer the system could not disambiguate from the text â€” surfaced so the
// user can pick instead of the system guessing (provenance stays deterministic).
export interface ResolveCandidate {
  customer_id: string;
  name: string;
  deal_id?: string | null;
}

// One retrieval event surfaced by a tool â€” the Retrieval Explorer's data.
export interface RetrievalItem {
  id: string;
  customer?: string | null;
  customer_id?: string;
  score: number;
  text?: string;
}
export interface RetrievalTrace {
  source: string;            // "notes_semantic" | "knowledge_keyword" | "graph"
  scope: string;             // "account:<id>" | "all"
  items: RetrievalItem[];
  query?: string;
  mode?: string;
  customer?: string | null;
  intent?: string;
}

export type ChatEvent =
  | { type: "start"; model?: string; endpoint?: string; role?: ChatRole }
  | { type: "artifact_meta"; kind: ArtifactKind; entity_ref?: EntityRef }
  | { type: "tool"; name: string; args: string; result: string; retrieval?: RetrievalTrace[]; document?: GeneratedDocument; batchId?: string | null; intent?: string }
  | { type: "routing"; think: boolean; reason: string; confidence: number; mode: "reasoning" | "fast" }
  | { type: "resolve"; status: "resolved" | "ambiguous" | "not_found"; query: string; customer?: unknown; candidates?: ResolveCandidate[] }
  | { type: "context"; status: "active"; conversation_id?: string; deal_id?: string | null; customer?: unknown; cached?: boolean }
  | { type: "deal_choices"; status: "ambiguous"; deals: unknown[] }
  | { type: "deal_ids"; deal_ids: string[] }
  | { type: "source"; key: string; label: string; status: "found" | "not_found" | "ambiguous" | "skipped" | "error"; count?: number; detail?: string }
  | { type: "web"; status: "found" | "not_found" | "error"; query: string; answer?: string; results?: { title?: string; url?: string; content?: string }[]; live?: boolean; reason?: string }
  | { type: "delta"; text: string }
  | { type: "answer"; text: string }
  | { type: "done"; model?: string }
  | { type: "unavailable"; reason?: string }
  | { type: "error"; reason?: string };

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

/**
 * Stream one assistant turn through the tool loop. Resolves when the stream
 * ends. Any transport failure surfaces as an `error` event (never throws).
 */
export async function chatStream(
  message: string,
  history: ChatTurn[],
  role: ChatRole,
  onEvent: (e: ChatEvent) => void,
  opts?: { signal?: AbortSignal; conversationId?: string; context?: string; dealId?: string },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message, history, role,
        conversation_id: opts?.conversationId,
        context: opts?.context ?? "",
        // The deal the user picked from the selector rides as a STRUCTURED field,
        // not appended to the message prose — the backend scopes to it directly.
        deal_id: opts?.dealId,
      }),
      cache: "no-store",
      signal: opts?.signal,
    });
  } catch {
    console.error(`network error`); onEvent({ type: "error", reason: "network" });
    return;
  }
  if (!res.ok || !res.body) {
    console.error(`http error: ${res.status}`); onEvent({ type: "error", reason: `http_${res.status}` });
    return;
  }
  await readSSE(res, (obj) => onEvent(obj as ChatEvent), () =>
    onEvent({ type: "error", reason: "stream" }),
  );
}

// --- Multi-agent crew (SSE) -------------------------------------------------
// A crew of role-specialised agents (Researcher / Coach / Strategist) analyse one
// deal together. The roster arrives first; then each agent streams its status, the
// tools it runs, and its written contribution; the Strategist's merged brief lands
// in `final`. See senpai.agent.crew on the backend.
export interface CrewAgentSpec {
  // "researcher" | "coach" | "strategist" for the deal crew, or a rep id (e.g. "R01")
  // for the manager fan-out â€” one lane per agent either way.
  id: string;
  label: string;
  role: string;
  emoji: string;
}
export type CrewEvent =
  | { type: "crew"; mode?: "team"; deal_id?: string; customer?: string; deal_name?: string; product_category?: string; agents: CrewAgentSpec[] }
  | { type: "agent"; id: string; status: "running" | "done" | "error"; contribution?: string; elapsed?: number; reason?: string }
  | { type: "agent_tool"; agent_id: string; name: string; summary: string }
  | { type: "resolve"; status: "ambiguous"; query: string; candidates: ResolveCandidate[] }
  | { type: "final"; markdown: string; elapsed?: number }
  | { type: "done" }
  | { type: "error"; reason?: string };

/** Stream a multi-agent crew analysis of one deal. Pass a deal id, or free text
 *  ("fujimoto") that the backend resolves to the customer's worst open deal.
 *  Resolves when the stream ends. */
export async function crewStream(
  target: { dealId?: string; message?: string },
  onEvent: (e: CrewEvent) => void,
  opts?: { signal?: AbortSignal },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/agent/crew`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deal_id: target.dealId, message: target.message }),
      cache: "no-store",
      signal: opts?.signal,
    });
  } catch {
    console.error(`network error`); onEvent({ type: "error", reason: "network" });
    return;
  }
  if (!res.ok || !res.body) {
    console.error(`http error: ${res.status}`); onEvent({ type: "error", reason: `http_${res.status}` });
    return;
  }
  await readSSE(res, (obj) => onEvent(obj as CrewEvent), () =>
    onEvent({ type: "error", reason: "stream" }),
  );
}

/** INTERNAL admin demo: stream a live Graph-RAG run — graph traversal events, the
 *  real retrieval trace, and a MEASURED head-to-head vs traditional retrieval.
 *  Never throws; transport failures surface as a synthetic `done`. */
export async function graphRagStream(
  query: string,
  onEvent: (e: GraphRagEvent) => void,
  opts?: { signal?: AbortSignal },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/admin/graph-rag/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
      cache: "no-store",
      signal: opts?.signal,
    });
  } catch {
    onEvent({ type: "done" });
    return;
  }
  if (!res.ok || !res.body) {
    onEvent({ type: "done" });
    return;
  }
  await readSSE(res, (obj) => onEvent(obj as GraphRagEvent), () =>
    onEvent({ type: "done" }),
  );
}

/** Stream the manager fan-out: one analyst agent per rep in parallel, then a team
 *  lead synthesis. Same CrewEvent contract as crewStream (agents = reps). */
export async function teamStream(
  onEvent: (e: CrewEvent) => void,
  opts?: { signal?: AbortSignal },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/agent/team`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      signal: opts?.signal,
    });
  } catch {
    console.error(`network error`); onEvent({ type: "error", reason: "network" });
    return;
  }
  if (!res.ok || !res.body) {
    console.error(`http error: ${res.status}`); onEvent({ type: "error", reason: `http_${res.status}` });
    return;
  }
  await readSSE(res, (obj) => onEvent(obj as CrewEvent), () =>
    onEvent({ type: "error", reason: "stream" }),
  );
}

// --- Streaming account commentary (SSE) -------------------------------------
// Senior account-manager read over a whole customer relationship. Mirrors
// narrateStream; any transport failure surfaces as an `unavailable` event.
export type AccountCommentaryEvent =
  | { type: "start"; model?: string; endpoint?: string }
  | { type: "artifact_meta"; kind: ArtifactKind; entity_ref?: EntityRef }
  | { type: "context"; customer?: string; customer_id?: string; score?: number; band?: string }
  | ({ type: "strategy" } & AccountStrategy)
  | { type: "delta"; text: string }
  | { type: "done"; model?: string }
  | { type: "unavailable"; reason?: string };

export async function accountCommentaryStream(
  customerId: string,
  onEvent: (e: AccountCommentaryEvent) => void,
  opts?: { lang?: "ja" | "en"; signal?: AbortSignal; conversationId?: string },
): Promise<void> {
  let res: Response;
  const qs = new URLSearchParams({ lang: opts?.lang ?? "ja" });
  if (opts?.conversationId) qs.set("conversation_id", opts.conversationId);
  try {
    res = await fetch(
      `${BASE}/api/account/${encodeURIComponent(customerId)}/commentary?${qs.toString()}`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        cache: "no-store", signal: opts?.signal },
    );
  } catch {
    onEvent({ type: "unavailable", reason: "network" });
    return;
  }
  if (!res.ok || !res.body) {
    onEvent({ type: "unavailable", reason: `http_${res.status}` });
    return;
  }
  await readSSE(res, (obj) => onEvent(obj as AccountCommentaryEvent), () =>
    onEvent({ type: "unavailable", reason: "stream" }),
  );
}

// --- shared SSE frame reader ------------------------------------------------
// Parses `data: {...}\n\n` frames from a streaming Response, invoking `onObj`
// per JSON frame. Used by both narrateStream and chatStream.
async function readSSE(
  res: Response,
  onObj: (obj: unknown) => void,
  onFail: () => void,
): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const frames = buf.split("\n\n");
      buf = frames.pop() ?? ""; // keep the trailing partial frame
      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        try {
          onObj(JSON.parse(line.slice(5).trim()));
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  } catch {
    onFail();
  }
}
