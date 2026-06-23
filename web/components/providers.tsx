"use client";

import { LangProvider, type Lang } from "@/lib/i18n";
import { SessionProvider, type Role } from "@/lib/session";
import { TooltipProvider } from "@/components/ui/tooltip";

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
      <SessionProvider initial={initialRole}>
        <TooltipProvider delayDuration={150}>{children}</TooltipProvider>
      </SessionProvider>
    </LangProvider>
  );
}
