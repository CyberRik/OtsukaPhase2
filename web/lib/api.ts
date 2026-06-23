// Typed client for the Senpai FastAPI bridge. Every call falls back to the
// committed fixtures when the API is unreachable, so the demo never shows a
// broken screen — it shows real-shaped data and a small "offline" hint.

import {
  COACH_EXAMPLES,
  COACH_FALLBACK,
  COACHING_FALLBACK,
  DASHBOARD_FALLBACK,
  GROWTH_FALLBACK,
  ITEMS_FALLBACK,
  PRINCIPLES_FALLBACK,
  SOURCES_FALLBACK,
} from "./fixtures";
import type {
  AccountSummary,
  CoachExample,
  CoachingWorkspace,
  CoachResponse,
  DashboardData,
  DealDetail,
  GrowthResponse,
  KnowledgeItem,
  Principle,
  SimilarCase,
  Source,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

export interface Fetched<T> {
  data: T;
  live: boolean;
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

export const api = {
  dashboard: (rep?: string) =>
    get<DashboardData>(
      `/api/dashboard${rep && rep !== "(all)" ? `?rep=${encodeURIComponent(rep)}` : ""}`,
      DASHBOARD_FALLBACK,
    ),
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
      { principles: PRINCIPLES_FALLBACK, counts: { total: 11, approved: 4, two_source: 4 } },
    ),
  items: () =>
    get<{ items: KnowledgeItem[]; counts: Record<string, number> }>(
      "/api/knowledge/items",
      { items: ITEMS_FALLBACK, counts: { total: 4, approved: 4, pending: 0 } },
    ),
  sources: () =>
    get<{ sources: Source[] }>("/api/knowledge/sources", { sources: SOURCES_FALLBACK }),
  growth: (rep?: string) =>
    get<GrowthResponse>(`/api/growth${rep ? `?rep=${encodeURIComponent(rep)}` : ""}`, GROWTH_FALLBACK),
  coaching: () => get<CoachingWorkspace>("/api/coaching", COACHING_FALLBACK),
  account: (customerId: string) =>
    get<AccountSummary | null>(`/api/account/${encodeURIComponent(customerId)}`, null),
};

// --- Streaming senior commentary (SSE from the vLLM-backed bridge) ----------
export type NarrateEvent =
  | { type: "start"; model?: string; endpoint?: string }
  | { type: "thinking"; chars: number }
  | { type: "context"; grounded: boolean; customer?: string | null; deal_id?: string | null; cached?: boolean; candidates?: ResolveCandidate[] }
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
    onEvent({ type: "error", reason: "network" });
    return;
  }
  if (!res.ok || !res.body) {
    onEvent({ type: "error", reason: `http_${res.status}` });
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

// A customer the system could not disambiguate from the text — surfaced so the
// user can pick instead of the system guessing (provenance stays deterministic).
export interface ResolveCandidate {
  customer_id: string;
  name: string;
  deal_id?: string | null;
}

// One retrieval event surfaced by a tool — the Retrieval Explorer's data.
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
  | { type: "tool"; name: string; args: string; result: string; retrieval?: RetrievalTrace[] }
  | { type: "routing"; think: boolean; reason: string; confidence: number; mode: "reasoning" | "fast" }
  | { type: "resolve"; status: "resolved" | "ambiguous" | "not_found"; query: string; customer?: unknown; candidates?: ResolveCandidate[] }
  | { type: "context"; status: "active"; conversation_id?: string; deal_id?: string | null; customer?: unknown; cached?: boolean }
  | { type: "deal_choices"; status: "ambiguous"; deals: unknown[] }
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
  opts?: { signal?: AbortSignal; conversationId?: string },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history, role, conversation_id: opts?.conversationId }),
      cache: "no-store",
      signal: opts?.signal,
    });
  } catch {
    onEvent({ type: "error", reason: "network" });
    return;
  }
  if (!res.ok || !res.body) {
    onEvent({ type: "error", reason: `http_${res.status}` });
    return;
  }
  await readSSE(res, (obj) => onEvent(obj as ChatEvent), () =>
    onEvent({ type: "error", reason: "stream" }),
  );
}

// --- Streaming account commentary (SSE) -------------------------------------
// Senior account-manager read over a whole customer relationship. Mirrors
// narrateStream; any transport failure surfaces as an `unavailable` event.
export type AccountCommentaryEvent =
  | { type: "start"; model?: string; endpoint?: string }
  | { type: "context"; customer?: string; customer_id?: string; score?: number; band?: string }
  | { type: "delta"; text: string }
  | { type: "done"; model?: string }
  | { type: "unavailable"; reason?: string };

export async function accountCommentaryStream(
  customerId: string,
  onEvent: (e: AccountCommentaryEvent) => void,
  opts?: { lang?: "ja" | "en"; signal?: AbortSignal },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(
      `${BASE}/api/account/${encodeURIComponent(customerId)}/commentary?lang=${opts?.lang ?? "ja"}`,
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
