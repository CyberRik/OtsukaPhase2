import { cn } from "@/lib/utils";
import Image from "next/image";

// Enterprise mark: Using the newly generated Senpai logo image
export function Brand({ compact = false, tagline }: { compact?: boolean; tagline?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-[8px] shadow-sm">
        <Image src="/logo.png" alt="Senpai Logo" width={32} height={32} className="object-cover" />
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
