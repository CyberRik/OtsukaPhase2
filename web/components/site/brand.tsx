import { cn } from "@/lib/utils";

// Enterprise mark: a deep-navy rounded tile with 先 ("senpai/senior") in white
// and a small indigo accent dot. Calm, professional — not an AI sparkle.
export function Brand({ compact = false, tagline }: { compact?: boolean; tagline?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative flex h-8 w-8 items-center justify-center rounded-[8px] bg-navy font-jp text-[15px] font-semibold text-white">
        先
        <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-primary ring-2 ring-card" />
      </div>
      {!compact && (
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight text-foreground">Senpai</div>
          {tagline && (
            <div className={cn("text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground")}>
              {tagline}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
