"use client";

import { useState } from "react";
import {
  Bot,
  Building2,
  ChevronDown,
  Database,
  Search,
  type LucideIcon,
  Layers,
  Lightbulb,
} from "lucide-react";
import type { Artifact, EvidenceRef } from "@/lib/artifacts";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

const ICONS: Record<string, LucideIcon> = { search: Search };

const EVIDENCE_LABEL: Record<EvidenceRef["kind"], string> = {
  deal: "Deal", spr: "SPR", principle: "Principle", playbook: "Playbook", web: "Web",
};

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

function SectionBlock({
  titleJa, titleEn, icon, body, lang,
}: { titleJa: string; titleEn: string; icon?: string; body: string[]; lang: "ja" | "en" }) {
  const Icon = (icon && ICONS[icon]) || Lightbulb;
  if (!body.length) return null;
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className={cn("text-[13.5px] font-medium text-foreground", lang === "ja" && "font-jp")}>
          {lang === "ja" ? titleJa : titleEn}
        </span>
      </div>
      <ul className="space-y-2">
        {body.map((it, i) => (
          <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed text-foreground/90">
            <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-primary/50" />
            <span className="flex-1">{inlineBold(it)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ResearchCard({ artifact }: { artifact: Artifact }) {
  const { lang } = useT();
  const [showEvidence, setShowEvidence] = useState(false);

  return (
    <div className="space-y-4 rounded-2xl border border-primary/20 bg-card p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <span className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Search className="h-4 w-4" />
          </span>
          <span className="text-[14px] font-semibold tracking-tight">
            {lang === "ja" ? "リサーチ" : "Research"}
          </span>
          {artifact.entity?.name && (
            <span className="inline-flex items-center gap-1 font-jp text-[12.5px] text-muted-foreground">
              <Building2 className="h-3.5 w-3.5" />
              {artifact.entity.name}
            </span>
          )}
        </span>
      </div>

      <div className="space-y-3">
        {artifact.sections.map((s) => (
          <SectionBlock key={s.key} titleJa={s.titleJa} titleEn={s.titleEn}
            icon={s.icon} body={s.body} lang={lang} />
        ))}
      </div>

      {artifact.commentary && (
        <div className="rounded-xl border border-primary/25 bg-primary/[0.02] p-4">
          <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-primary">
            <Bot className="h-3.5 w-3.5" /> {lang === "ja" ? "回答" : "Answer"}
            {artifact.status === "building" && (
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
            )}
          </div>
          <Markdown text={artifact.commentary} />
        </div>
      )}

      <div>
        <button
          onClick={() => setShowEvidence((v) => !v)}
          className="flex w-full items-center justify-between gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-left transition-colors hover:border-primary/40"
        >
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-foreground">
            <Layers className="h-3.5 w-3.5 text-muted-foreground" />
            {lang === "ja" ? "根拠・出典" : "Evidence / Provenance"}
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              {artifact.evidence.length}
            </span>
          </span>
          <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", showEvidence && "rotate-180")} />
        </button>
        {showEvidence && (
          <div className="animate-fade-up mt-3 rounded-xl border border-border bg-muted/20 p-3">
            {artifact.evidence.length === 0 ? (
              <p className="text-[12.5px] text-muted-foreground">
                {lang === "ja" ? "構造化された出典はありません。" : "No structured sources."}
              </p>
            ) : (
              <ul className="flex flex-wrap gap-2">
                {artifact.evidence.map((e) => (
                  <li key={`${e.kind}:${e.id}`}>
                    {e.url ? (
                      <a href={e.url} target="_blank" rel="noopener noreferrer"
                         className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11.5px] hover:border-primary/40">
                        <Database className="h-3 w-3 text-muted-foreground" />
                        <span className="text-muted-foreground">{EVIDENCE_LABEL[e.kind]}</span>
                        <span className="font-mono text-foreground">{e.id}</span>
                      </a>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11.5px]">
                        <Database className="h-3 w-3 text-muted-foreground" />
                        <span className="text-muted-foreground">{EVIDENCE_LABEL[e.kind]}</span>
                        <span className="font-mono text-foreground">{e.id}</span>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
