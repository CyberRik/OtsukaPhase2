"use client";

import Image from "next/image";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/**
 * Co-branding mark: identifies Senpai as prepared for the client, Otsuka Shokai.
 * The client wordmark (大塚商会) is rendered small and muted so it reads as
 * provenance, not a competing brand.
 */
export function ClientBadge({ className }: { className?: string }) {
  const { t } = useT();
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span className="eyebrow hidden text-muted-foreground sm:inline">{t("app.builtFor")}</span>
      <Image
        src="/otsuka-shokai.png"
        alt="Otsuka Shokai"
        width={783}
        height={203}
        priority
        className="h-[28px] w-auto opacity-90"
      />
    </div>
  );
}
