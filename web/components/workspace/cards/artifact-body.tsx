"use client";

// Unified artifact renderer for every skill output (review / account_brief /
// research). One component, driven by a small per-kind config — replaces the
// three near-identical card files that had begun to drift. The shape is always:
//
//   header (kind label + entity + band)
//   [alert section]            ← red intercept (review: reality_check, account: risk)
//   [commentary]               ← streamed senior read / answer (position varies)
//   sections                   ← the deterministic lenses
//   evidence / provenance      ← collapsible, deterministic IDs only
//
// The structured `sections` are the deterministic record; `commentary` is the
// streamed presentation layer. Evidence carries source IDs only, never names.

import { useState } from "react";
import {
  AlertTriangle, Bot, Building2, ChevronDown, Database, Eye,
  FileSpreadsheet, FileText, Layers, Lightbulb, MessagesSquare, Route, Scale, Search, Sparkles, Target, type LucideIcon,
} from "lucide-react";
import type { Artifact, ArtifactKind, EvidenceRef } from "@/lib/artifacts";
import type { Confidence } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { downloadArtifact, downloadArtifactDocx } from "@/lib/artifact-export";
import { SourceChips } from "@/components/source-chip";
import { ConfidenceBadge } from "@/components/confidence-badge";

const ICONS: Record<string, LucideIcon> = {
  eye: Eye, search: Search, alert: AlertTriangle,
  message: MessagesSquare, route: Route, scale: Scale, target: Target,
};

const BAND_CHIP: Record<string, string> = {
  red: "bg-band-red/10 text-band-red",
  yellow: "bg-band-yellow/10 text-band-yellow",
  green: "bg-conf-high/10 text-conf-high",
};

const EVIDENCE_LABEL: Record<EvidenceRef["kind"], string> = {
  deal: "Deal", spr: "SPR", principle: "Principle", playbook: "Playbook", web: "Web",
};

// Per-kind presentation. `alertKey` is the section rendered as a red intercept;
// `commentaryAfter` puts the streamed block below the sections (research reads
// "sources, then answer"); the rest is the header + commentary labelling.
type KindMeta = {
  icon: LucideIcon;
  labelJa: string; labelEn: string;
  alertKey: string | null;
  commentaryAfter: boolean;
  commentaryJa: string; commentaryEn: string;
};
const KIND_META: Record<ArtifactKind, KindMeta> = {
  review: {
    icon: Bot, labelJa: "レビュー", labelEn: "Review",
    alertKey: "reality_check", commentaryAfter: false,
    commentaryJa: "先輩の見立て", commentaryEn: "Senior's read",
  },
  account_brief: {
    icon: Building2, labelJa: "アカウント概要", labelEn: "Account Brief",
    alertKey: "risk", commentaryAfter: false,
    commentaryJa: "先輩の見立て", commentaryEn: "Senior's read",
  },
  research: {
    icon: Search, labelJa: "リサーチ", labelEn: "Research",
    alertKey: null, commentaryAfter: true,
    commentaryJa: "回答", commentaryEn: "Answer",
  },
};

// --- lightweight inline markdown (bold labels: **状況:** …) ------------------
function inlineBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>,
  );
}

function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  return (
    <div className="space-y-1.5 font-jp text-[13.5px] leading-relaxed text-foreground/90">
      {lines.map((ln, i) => {
        const tx = ln.trim();
        if (!tx) return <div key={i} className="h-1" />;
        if (/^---+$/.test(tx)) return <div key={i} className="my-1 border-t border-border" />;
        if (/^#{1,6}\s/.test(tx)) {
          return (
            <h4 key={i} className="pt-2 text-[12px] font-semibold uppercase tracking-[0.04em] text-primary">
              {tx.replace(/^#{1,6}\s+/, "")}
            </h4>
          );
        }
        if (/^[-*]\s/.test(tx)) {
          return (
            <div key={i} className="flex gap-2 pl-1">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-primary/60" />
              <span>{inlineBold(tx.replace(/^[-*]\s+/, ""))}</span>
            </div>
          );
        }
        return <p key={i}>{inlineBold(tx)}</p>;
      })}
    </div>
  );
}

// A senior-tip line carries its provenance inline:
//   先輩の知見(出典 PB12・P03 / 確度high): <tip>
// Parse the 出典/確度 chrome into source chips + a confidence badge so the tip
// reads as grounded evidence, not a raw string (parity with the Review Coach).
const SENIOR_RE = /^先輩の知見\(出典 (.+?) \/ 確度(.+?)\): ([\s\S]+)$/;

function SeniorTip({ raw, label }: { raw: string; label: string }) {
  const m = raw.match(SENIOR_RE);
  if (!m) return <span className="flex-1">{inlineBold(raw)}</span>;
  const [, srcs, conf, tip] = m;
  const ids = srcs.split("・").map((s) => s.trim()).filter((s) => s && s !== "—");
  return (
    <div className="flex-1 rounded-lg border border-primary/20 bg-primary/[0.04] p-2.5">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-primary">
          <Sparkles className="h-3 w-3" /> {label}
        </span>
        <SourceChips ids={ids} />
        <ConfidenceBadge level={(conf.trim() as Confidence) || "unverified"} />
      </div>
      <span className="block text-[13px] leading-relaxed text-foreground/90">{inlineBold(tip)}</span>
    </div>
  );
}

function SectionBlock({
  titleJa, titleEn, icon, body, lang, seniorLabel,
}: { titleJa: string; titleEn: string; icon?: string; body: string[]; lang: "ja" | "en"; seniorLabel: string }) {
  const Icon = (icon && ICONS[icon]) || Lightbulb;
  if (!body.length) return null;
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className={cn("text-[13.5px] font-medium text-foreground", lang === "ja" && "font-jp")}>
          {lang === "ja" ? titleJa : titleEn}
        </span>
      </div>
      <ul className="space-y-2">
        {body.map((it, i) =>
          it.startsWith("先輩の知見") ? (
            <li key={i} className="flex">
              <SeniorTip raw={it} label={seniorLabel} />
            </li>
          ) : (
            <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed text-foreground/90">
              <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-primary/50" />
              <span className="flex-1">{inlineBold(it)}</span>
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

function CommentaryBlock({ artifact, label }: { artifact: Artifact; label: string }) {
  if (!artifact.commentary && artifact.status !== "building") return null;
  return (
    <div className="border-l-2 border-primary/40 pl-4 py-1">
      <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-primary">
        <Bot className="h-3.5 w-3.5" /> {label}
        {artifact.status === "building" && (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        )}
      </div>
      {artifact.commentary ? (
        <Markdown text={artifact.commentary} />
      ) : (
        <div className="space-y-2 mt-3 w-3/4 opacity-40">
          <div className="h-3 w-full animate-pulse rounded-full bg-muted-foreground/30" />
          <div className="h-3 w-5/6 animate-pulse rounded-full bg-muted-foreground/30" />
          <div className="h-3 w-4/6 animate-pulse rounded-full bg-muted-foreground/30" />
        </div>
      )}
    </div>
  );
}

function EvidenceDrawer({ artifact, lang }: { artifact: Artifact; lang: "ja" | "en" }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-left transition-colors hover:border-primary/40"
      >
        <span className="flex items-center gap-1.5 text-[13px] font-medium text-foreground">
          <Layers className="h-3.5 w-3.5 text-muted-foreground" />
          {lang === "ja" ? "根拠・出典" : "Evidence / Provenance"}
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {artifact.evidence.length}
          </span>
        </span>
        <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="animate-fade-up mt-3 rounded-xl border border-border bg-muted/20 p-3">
          {artifact.evidence.length === 0 ? (
            <p className="text-[12.5px] text-muted-foreground">
              {lang === "ja" ? "構造化された出典はありません。" : "No structured sources."}
            </p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {artifact.evidence.map((e) => {
                const inner = (
                  <>
                    <Database className="h-3 w-3 text-muted-foreground" />
                    <span className="text-muted-foreground">{EVIDENCE_LABEL[e.kind]}</span>
                    <span className="font-mono text-foreground">{e.id}</span>
                  </>
                );
                return (
                  <li key={`${e.kind}:${e.id}`}>
                    {e.url ? (
                      <a href={e.url} target="_blank" rel="noopener noreferrer"
                         className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11.5px] hover:border-primary/40">
                        {inner}
                      </a>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11.5px]">
                        {inner}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export function ArtifactBody({ artifact }: { artifact: Artifact }) {
  const { lang } = useT();
  const meta = KIND_META[artifact.kind];
  const HeaderIcon = meta.icon;

  const alert = meta.alertKey
    ? artifact.sections.find((s) => s.key === meta.alertKey)
    : undefined;
  const sections = artifact.sections.filter((s) => s.key !== meta.alertKey);
  const commentary = (
    <CommentaryBlock artifact={artifact} label={lang === "ja" ? meta.commentaryJa : meta.commentaryEn} />
  );

  return (
    <div className="space-y-4 rounded-xl border border-border bg-card p-5">
      {/* header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <span className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <HeaderIcon className="h-4 w-4" />
          </span>
          <span className="text-[14px] font-semibold tracking-tight">
            {lang === "ja" ? meta.labelJa : meta.labelEn}
          </span>
          {artifact.entity?.name && (
            <span className="inline-flex items-center gap-1 font-jp text-[12.5px] text-muted-foreground">
              <Building2 className="h-3.5 w-3.5" />
              {artifact.entity.name}
              {artifact.entity.type === "deal" && (
                <span className="font-mono text-[10.5px]">{artifact.entity.id}</span>
              )}
            </span>
          )}
        </span>
        <span className="flex items-center gap-2">
          {artifact.band && (
            <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase", BAND_CHIP[artifact.band])}>
              {artifact.band}
            </span>
          )}
          {artifact.status === "ready" && (
            <>
              <button
                onClick={() => { void downloadArtifact(artifact, lang); }}
                title={lang === "ja" ? "Excel (.xlsx) で書き出す" : "Export to Excel (.xlsx)"}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                <FileSpreadsheet className="h-3.5 w-3.5" />
                Excel
              </button>
              <button
                onClick={() => { void downloadArtifactDocx(artifact, lang); }}
                title={lang === "ja" ? "Word (.docx) で書き出す" : "Export to Word (.docx)"}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                <FileText className="h-3.5 w-3.5" />
                Word
              </button>
            </>
          )}
        </span>
      </div>

      {/* alert intercept (review reality_check / account risk) */}
      {alert && alert.body.length > 0 && (
        <div className="rounded-xl border border-band-red/40 bg-band-red/5 p-4">
          <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-band-red">
            <AlertTriangle className="h-4 w-4" />
            {lang === "ja" ? alert.titleJa : alert.titleEn}
          </div>
          <ul className="space-y-1.5">
            {alert.body.map((it, i) => (
              <li key={i} className="text-[12.5px] leading-snug text-foreground/90">{inlineBold(it)}</li>
            ))}
          </ul>
        </div>
      )}

      {!meta.commentaryAfter && commentary}

      <div className="space-y-3">
        {sections.map((s) => (
          <SectionBlock key={s.key} titleJa={s.titleJa} titleEn={s.titleEn}
            icon={s.icon} body={s.body} lang={lang}
            seniorLabel={lang === "ja" ? "先輩の知見" : "Senior's insight"} />
        ))}
      </div>

      {meta.commentaryAfter && commentary}

      <EvidenceDrawer artifact={artifact} lang={lang} />
    </div>
  );
}
