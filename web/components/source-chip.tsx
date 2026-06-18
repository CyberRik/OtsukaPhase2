import { cn } from "@/lib/utils";

// A citation chip — the source a piece of knowledge traces back to. Subtle and
// modern: interviews (I…) get a quiet indigo accent; the instrument (Q…) neutral.
export function SourceChip({ id, className }: { id: string; className?: string }) {
  const isInterview = id.startsWith("I");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium tracking-tight",
        isInterview
          ? "border-primary/25 bg-primary/[0.06] text-primary"
          : "border-border bg-muted text-muted-foreground",
        className,
      )}
    >
      {isInterview && <span className="h-1 w-1 rounded-full bg-primary" />}
      {id}
    </span>
  );
}

export function SourceChips({ ids, className }: { ids: string[]; className?: string }) {
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1", className)}>
      {ids.length ? ids.map((id) => <SourceChip key={id} id={id} />) : <span className="text-muted-foreground">—</span>}
    </span>
  );
}
