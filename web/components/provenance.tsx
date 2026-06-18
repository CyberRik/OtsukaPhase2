import { Quote } from "lucide-react";
import { SourceChip } from "./source-chip";
import type { Citation } from "@/lib/types";

// The verbatim interview span a principle rests on. This is the heart of the
// "no synthetic expertise" promise — every claim shows the sentence it came from.
export function ProvenanceQuote({ citation }: { citation: Citation }) {
  return (
    <figure className="space-y-1.5">
      <blockquote className="quote-jp">{citation.quote}</blockquote>
      <figcaption className="flex items-center gap-2 pl-4 text-[11px] text-muted-foreground">
        <SourceChip id={citation.source_id} />
        {citation.location && <span className="font-mono">{citation.location}</span>}
        <span>一次情報 (interview verbatim)</span>
      </figcaption>
    </figure>
  );
}

export function ProvenanceList({ citations }: { citations: Citation[] }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Quote className="h-3.5 w-3.5" />
        <span className="eyebrow">Traceable to source</span>
      </div>
      {citations.map((c, i) => (
        <ProvenanceQuote key={`${c.source_id}-${i}`} citation={c} />
      ))}
    </div>
  );
}
