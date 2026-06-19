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
};

// --- Streaming senior commentary (SSE from the vLLM-backed bridge) ----------
export type NarrateEvent =
  | { type: "start"; model?: string; endpoint?: string }
  | { type: "thinking"; chars: number }
  | { type: "context"; grounded: boolean; customer?: string | null; deal_id?: string | null }
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
  opts?: { lang?: "ja" | "en"; signal?: AbortSignal },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/coach/narrate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note, deal_id, narrate: true, lang: opts?.lang ?? "ja" }),
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

export type ChatEvent =
  | { type: "start"; model?: string; endpoint?: string; role?: ChatRole }
  | { type: "tool"; name: string; args: string; result: string }
  | { type: "answer"; text: string }
  | { type: "done"; model?: string }
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
  opts?: { signal?: AbortSignal },
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history, role }),
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
