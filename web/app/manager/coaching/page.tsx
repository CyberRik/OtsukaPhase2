"use client";

import { useT } from "@/lib/i18n";
import { PageHeader } from "@/components/site/page-header";

export default function ManagerCoachingPage() {
  const { t } = useT();
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.coaching"
        titleKey="coaching.title"
        leadKey="coaching.lead"
      />
      <div className="rounded-xl border border-dashed border-border p-12 text-center text-[14px] text-muted-foreground">
        {t("coaching.none")}
      </div>
    </div>
  );
}
