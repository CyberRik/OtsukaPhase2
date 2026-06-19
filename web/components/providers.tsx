"use client";

import { LangProvider, type Lang, useT } from "@/lib/i18n";
import { SessionProvider, type Role } from "@/lib/session";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Globe } from "lucide-react";

function TranslationBarrier({ children }: { children: React.ReactNode }) {
  const { isTransitioning, pendingCount } = useT();

  return (
    <>
      {children}
      {isTransitioning && (
        <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-background/80 backdrop-blur-md transition-all duration-300 animate-in fade-in">
          <div className="flex flex-col items-center gap-4 rounded-2xl border border-border bg-card p-8 shadow-2xl">
            <div className="relative flex h-12 w-12 items-center justify-center">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/20 opacity-75" />
              <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Globe className="h-5 w-5 animate-spin" style={{ animationDuration: "3s" }} />
              </div>
            </div>
            <div className="space-y-1.5 text-center">
              <h3 className="text-sm font-semibold text-foreground">Translating page contents...</h3>
              <p className="text-[11px] text-muted-foreground">
                {pendingCount > 0 
                  ? `Preparing English views (${pendingCount} items remaining)` 
                  : "Finishing up..."}
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function Providers({
  initialLang,
  initialRole,
  children,
}: {
  initialLang: Lang;
  initialRole: Role | null;
  children: React.ReactNode;
}) {
  return (
    <LangProvider initial={initialLang}>
      <TranslationBarrier>
        <SessionProvider initial={initialRole}>
          <TooltipProvider delayDuration={150}>{children}</TooltipProvider>
        </SessionProvider>
      </TranslationBarrier>
    </LangProvider>
  );
}
