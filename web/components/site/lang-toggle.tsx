"use client";

import { Globe } from "lucide-react";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// Persistent JA | EN switch. Japanese is the default.
export function LangToggle({ className }: { className?: string }) {
  const { lang, setLang } = useT();
  return (
    <div className={cn("inline-flex items-center gap-1 rounded-lg border border-border bg-card p-0.5", className)}>
      <Globe className="ml-1.5 h-3.5 w-3.5 text-muted-foreground" />
      {(["ja", "en"] as const).map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          className={cn(
            "rounded-md px-2 py-1 text-[12px] font-medium transition-colors",
            lang === l ? "bg-navy text-navy-foreground" : "text-muted-foreground hover:text-foreground",
          )}
          aria-pressed={lang === l}
        >
          {l === "ja" ? "日本語" : "English"}
        </button>
      ))}
    </div>
  );
}
