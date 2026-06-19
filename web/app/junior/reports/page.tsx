"use client";

import { useT } from "@/lib/i18n";
import { PageHeader } from "@/components/site/page-header";

export default function JuniorReportsPage() {
  const { t } = useT();
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.reports"
        titleKey="reports.title"
        leadKey="reports.lead"
      />
      <div className="rounded-xl border border-dashed border-border p-12 text-center text-[14px] text-muted-foreground">
        {t("reports.empty")}
      </div>
    </div>
  );
}
