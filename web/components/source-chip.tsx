import { cn } from "@/lib/utils";

// A citation chip — the interview a piece of knowledge traces back to.
// Interviews (I…) get the vermilion seal; the instrument (Q…) is neutral.
export function SourceChip({ id, className }: { id: string; className?: string }) {
  const isInterview = id.startsWith("I");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium tracking-tight",
        isInterview
          ? "border-vermilion/30 bg-vermilion/5 text-vermilion"
          : "border-border bg-muted text-muted-foreground",
        className,
      )}
    >
      {isInterview && <span className="h-1 w-1 rounded-full bg-vermilion" />}
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
