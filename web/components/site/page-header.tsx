"use client";

import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// Translatable page header. Pass i18n keys; raw strings also work as a fallback.
export function PageHeader({
  eyebrowKey,
  titleKey,
  leadKey,
  children,
  className,
}: {
  eyebrowKey: string;
  titleKey: string;
  leadKey?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const { t } = useT();
  return (
    <header className={cn("flex flex-col gap-4 pb-2 md:flex-row md:items-end md:justify-between", className)}>
      <div className="max-w-2xl space-y-2">
        <div className="eyebrow text-primary">{t(eyebrowKey)}</div>
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight text-foreground md:text-[30px]">
          {t(titleKey)}
        </h1>
        {leadKey && <p className="text-[14px] leading-relaxed text-muted-foreground">{t(leadKey)}</p>}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </header>
  );
}
