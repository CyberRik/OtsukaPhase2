"use client";

import { Quote } from "lucide-react";
import { SourceChip } from "./source-chip";
import { useT } from "@/lib/i18n";
import type { Citation } from "@/lib/types";

// The verbatim interview span a principle rests on — the heart of the
// "no synthetic expertise" promise. Rendered subtly: a quiet indigo rule.
export function ProvenanceQuote({ citation }: { citation: Citation }) {
  const { t } = useT();
  return (
    <figure className="space-y-1.5">
      <blockquote className="quote-jp">{citation.quote}</blockquote>
      <figcaption className="flex flex-wrap items-center gap-2 pl-3.5 text-[11px] text-muted-foreground">
        <SourceChip id={citation.source_id} />
        {citation.location && <span className="font-mono">{citation.location}</span>}
        <span>{t("knowledge.verbatim")}</span>
      </figcaption>
    </figure>
  );
}

export function ProvenanceList({ citations }: { citations: Citation[] }) {
  const { t } = useT();
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Quote className="h-3.5 w-3.5" />
        <span className="eyebrow">{t("knowledge.traceable")}</span>
      </div>
      {citations.map((c, i) => (
        <ProvenanceQuote key={`${c.source_id}-${i}`} citation={c} />
      ))}
    </div>
  );
}
