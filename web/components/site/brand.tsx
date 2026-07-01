import { cn } from "@/lib/utils";

export function Brand({ compact = false, fullMark = false, tagline }: { compact?: boolean; fullMark?: boolean; tagline?: string }) {
  return (
    <div className="flex items-center gap-3">
      {/* Logo Mark */}
      <div className="flex h-[28px] items-center justify-center overflow-hidden rounded-[6px] bg-foreground px-3 text-background shadow-sm transition-transform hover:scale-[1.02]">
        <span className="whitespace-nowrap text-[14px] font-bold tracking-widest translate-y-[0.5px] ml-[2px]">先輩</span>
        {fullMark && (
          <>
            <div className="ml-2 h-3 w-[1px] bg-background/30" />
            <span className="ml-2 text-[11px] font-bold uppercase tracking-[0.2em] translate-y-[0.5px]">Senpai</span>
          </>
        )}
      </div>

      {/* Tagline */}
      {!compact && tagline && (
        <div className="hidden sm:block border-l border-border/60 pl-3">
          <div className="text-[9px] font-semibold uppercase tracking-widest text-muted-foreground leading-tight line-clamp-2 max-w-[140px] text-balance">
            {tagline}
          </div>
        </div>
      )}
    </div>
  );
}
