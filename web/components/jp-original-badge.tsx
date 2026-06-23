"use client";

import { Languages } from "lucide-react";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// Shown next to a piece of knowledge that is rendered in its Japanese original
// because no English translation exists yet. Honest signposting so an English
// reader knows the text below is untranslated source, not a UI bug.
export function JpOriginalBadge({ className }: { className?: string }) {
  const { t } = useT();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium leading-none text-muted-foreground",
        className,
      )}
      title={t("common.jpOriginal.why")}
    >
      <Languages className="h-3 w-3" />
      {t("common.jpOriginal")}
    </span>
  );
}
