// Senpai Workspace — the Artifact model.
//
// An Artifact is the typed, IMMUTABLE, grounded output of a skill (/review,
// /account, /research). It is a first-class entry in a chat thread, not free
// prose. Two invariants protect the product's trust proposition:
//   1. Immutability — a skill never edits an artifact in place. Re-running a
//      skill APPENDS a new artifact that `supersedes` the previous one, so an
//      artifact is always a faithful record of what was true, with what
//      evidence, at one moment.
//   2. Deterministic provenance — `evidence` carries source IDs only (deal /
//      SPR / principle / playbook / web), NEVER human names. The assemblers
//      below derive evidence from the deterministic engine output; the LLM is
//      never the source of an evidence entry.
//
// Phase 1: artifacts live client-side as typed thread entries (assembled from
// the existing /api/coach, /api/account, /api/chat payloads). No server schema.

import type { AccountSummary, CoachResponse } from "./types";

export type ArtifactKind = "review" | "account_brief" | "research";

// A deterministic pointer to a source record. Never a person.
export type EvidenceKind = "deal" | "spr" | "principle" | "playbook" | "web";
export interface EvidenceRef {
  kind: EvidenceKind;
  id: string;
  label?: string;
  url?: string;
}

// A domain object the artifact is about. Drives follow-up grounding: a bare
// chat turn after an artifact inherits this entity instead of re-resolving.
export interface EntityRef {
  type: "deal" | "account";
  id: string;
  name?: string;
}

export interface ArtifactSection {
  key: string;
  titleJa: string;
  titleEn: string;
  icon?: string;
  body: string[];
}

export type ArtifactStatus = "building" | "ready" | "unavailable";

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  threadId: string;
  turnId: string;
  entity?: EntityRef;
  band?: "red" | "yellow" | "green";
  sections: ArtifactSection[];
  evidence: EvidenceRef[];
  // The grounded senior read / synthesis (streamed). Presentation layer; the
  // structured `sections` remain the deterministic record.
  commentary?: string | null;
  live: boolean; // true when assembled from the live API, false from fixtures
  producedBy: string; // "review@1" | "account_brief@1" | "research@1"
  supersedes?: string;
  createdAt: number;
  status: ArtifactStatus;
}

export function newArtifactId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `art-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

// --- evidence extraction (deterministic, IDs only) --------------------------
// Senior-tip lines carry their structured provenance inline, e.g.
//   先輩の知見(出典 PB12・P03 / 確度high): …
// We parse the 出典 segment into IDs. We deliberately match only structured ID
// shapes (PB.., P.., I.., D..) so a stray human name can never become evidence.
const SENIOR_SRC_RE = /^先輩の知見\(出典 (.+?) \/ 確度.+?\):/;
const ID_RE = /^(PB\d+|P\d+|I\d+|D\d+)$/i;

function classifyId(id: string): EvidenceKind {
  if (/^PB/i.test(id)) return "playbook";
  if (/^D/i.test(id)) return "deal";
  return "principle"; // P.. / I..
}

function evidenceFromResult(result: Record<string, string[]>): EvidenceRef[] {
  const ids = new Set<string>();
  for (const arr of Object.values(result)) {
    for (const line of arr ?? []) {
      const m = line.match(SENIOR_SRC_RE);
      if (!m) continue;
      for (const raw of m[1].split("・")) {
        const id = raw.trim();
        if (id && id !== "—" && ID_RE.test(id)) ids.add(id.toUpperCase());
      }
    }
  }
  return [...ids].map((id) => ({ kind: classifyId(id), id }));
}

// --- /review → review artifact (pure, deterministic) ------------------------
// Maps the EXISTING /api/coach/review payload into a review artifact. This adds
// no facts: every section body and every evidence ID comes straight from the
// deterministic coach engine. `commentary` (the streamed senior read) is layered
// in separately by the caller as deltas arrive.
export function assembleReviewArtifact(
  resp: CoachResponse,
  opts: {
    threadId: string;
    turnId: string;
    live: boolean;
    entity?: EntityRef;
    commentary?: string | null;
    supersedes?: string;
  },
): Artifact {
  const sections: ArtifactSection[] = [];

  // Priority Actions (deterministic account imperatives) lead, mirroring the
  // current coaching card's "Top Priority Actions".
  const imperatives = resp.account_context?.deterministic_imperatives ?? [];
  if (imperatives.length) {
    sections.push({
      key: "priority_actions",
      titleJa: "取るべき次の一手",
      titleEn: "Priority Actions",
      icon: "route",
      body: imperatives,
    });
  }

  for (const s of resp.sections) {
    sections.push({
      key: s.key,
      titleJa: s.ja,
      titleEn: s.en,
      icon: s.icon,
      body: resp.result[s.key] ?? [],
    });
  }

  const evidence = evidenceFromResult(resp.result);
  if (opts.entity?.type === "deal") {
    evidence.unshift({ kind: "deal", id: opts.entity.id, label: opts.entity.name });
  }

  return {
    id: newArtifactId(),
    kind: "review",
    threadId: opts.threadId,
    turnId: opts.turnId,
    entity: opts.entity,
    sections,
    evidence,
    commentary: opts.commentary ?? null,
    live: opts.live,
    producedBy: "review@1",
    supersedes: opts.supersedes,
    createdAt: Date.now(),
    status: "ready",
  };
}

// --- /account → account_brief artifact (deterministic aggregation) ----------
// Maps the EXISTING /api/account/{id} payload (a deterministic roll-up) into an
// account_brief artifact. The senior account read streams into `commentary`
// separately. Evidence is the customer id plus the quote/order record ids.
const yen = (n: number) => "¥" + (n ?? 0).toLocaleString();

export function assembleAccountArtifact(
  s: AccountSummary,
  opts: { threadId: string; turnId: string; live: boolean; lang: "ja" | "en" },
): Artifact {
  const ja = opts.lang === "ja";
  const sections: ArtifactSection[] = [];

  sections.push({
    key: "overview", titleJa: "概要", titleEn: "Overview", icon: "eye",
    body: [
      `**${ja ? "業種" : "Industry"}:** ${s.industry || "—"} / ${s.size || "—"}`,
      `**${ja ? "案件" : "Deals"}:** ${ja ? "進行中" : "active"} ${s.active_deals} · ${ja ? "受注" : "won"} ${s.won_deals} · ${ja ? "失注" : "lost"} ${s.lost_deals}`,
      `**${ja ? "パイプライン" : "Pipeline"}:** ${yen(s.total_pipeline)} · **${ja ? "累計売上" : "Historical"}:** ${yen(s.historical_revenue)}`,
      `**${ja ? "直近活動" : "Last activity"}:** ${s.last_activity || "—"} (${s.activity_trend || "—"})`,
    ],
  });

  if (s.risk_signals?.length) {
    sections.push({
      key: "risk", titleJa: "リスクの兆候", titleEn: "Risk signals", icon: "alert",
      body: s.risk_signals.map((p) =>
        `**${ja ? p.label_ja : p.label_en}**${p.evidence ? ` — ${p.evidence}` : ""}`),
    });
  }

  if (s.expansion_signals?.length) {
    sections.push({
      key: "expansion", titleJa: "拡大の機会", titleEn: "Expansion opportunities", icon: "route",
      body: s.expansion_signals.map((g) => {
        const label = g.label_ja && ja ? g.label_ja : g.label_en || g.target || "";
        const detail = g.rationale || g.evidence || "";
        return `**${label}**${detail ? ` — ${detail}` : ""}`;
      }),
    });
  }

  if (s.recommended_focus) {
    sections.push({
      key: "focus", titleJa: "推奨される注力点", titleEn: "Recommended focus", icon: "scale",
      body: [s.recommended_focus],
    });
  }

  const evidence: EvidenceRef[] = [{ kind: "spr", id: s.customer_id, label: s.customer }];
  for (const q of s.recent_quotes ?? []) if (q.quote_id) evidence.push({ kind: "spr", id: q.quote_id });
  for (const o of s.recent_orders ?? []) if (o.order_id) evidence.push({ kind: "spr", id: o.order_id });

  return {
    id: newArtifactId(),
    kind: "account_brief",
    threadId: opts.threadId,
    turnId: opts.turnId,
    entity: { type: "account", id: s.customer_id, name: s.customer },
    band: s.health?.band,
    sections,
    evidence,
    commentary: null,
    live: opts.live,
    producedBy: "account_brief@1",
    createdAt: Date.now(),
    status: "ready",
  };
}

// --- /research → research artifact -----------------------------------------
// Assembled from the research_stream events (source statuses, the grounded
// answer, any web citations). The answer is the synthesis; sources/web are the
// evidence. This skill is LLM-driven (retrieval), which is acceptable because
// its output is explicitly a cited research note, not a verdict.
export interface ResearchSourceLine { label: string; status: string; count?: number }

export function assembleResearchArtifact(opts: {
  threadId: string; turnId: string; live: boolean; lang: "ja" | "en";
  answer: string; sources: ResearchSourceLine[]; webUrls: string[]; entity?: EntityRef;
}): Artifact {
  const ja = opts.lang === "ja";
  const sections: ArtifactSection[] = [];
  if (opts.sources.length) {
    sections.push({
      key: "sources", titleJa: "参照したソース", titleEn: "Sources consulted", icon: "search",
      body: opts.sources.map((s) =>
        `**${s.label}:** ${s.status}${s.count != null ? ` (${s.count})` : ""}`),
    });
  }

  const evidence: EvidenceRef[] = [];
  if (opts.entity) {
    evidence.push({ kind: opts.entity.type === "account" ? "spr" : "deal",
                    id: opts.entity.id, label: opts.entity.name });
  }
  for (const u of opts.webUrls) {
    let host = u;
    try { host = new URL(u).hostname.replace(/^www\./, ""); } catch { /* keep raw */ }
    evidence.push({ kind: "web", id: host, url: u });
  }

  return {
    id: newArtifactId(),
    kind: "research",
    threadId: opts.threadId,
    turnId: opts.turnId,
    entity: opts.entity,
    sections,
    evidence,
    commentary: opts.answer || null,
    live: opts.live,
    producedBy: "research@1",
    createdAt: Date.now(),
    status: "ready",
    band: undefined,
  };
}
