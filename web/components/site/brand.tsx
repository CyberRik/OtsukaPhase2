import { cn } from "@/lib/utils";

// The Senpai mark: a vermilion hanko-style seal with 先 (senpai/"senior"),
// next to an editorial wordmark. Deliberately not a generic AI sparkle.
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-vermilion font-jp text-lg font-semibold text-white shadow-sm">
        先
      </div>
      {!compact && (
        <div className="leading-tight">
          <div className="font-serif text-lg font-semibold tracking-tight text-foreground">Senpai</div>
          <div className={cn("text-[10px] uppercase tracking-eyebrow text-muted-foreground")}>
            Sales Knowledge
          </div>
        </div>
      )}
    </div>
  );
}
