import { api } from "@/lib/api";
import { PageHeader } from "@/components/site/page-header";
import { DashboardView } from "@/components/dashboard/dashboard-view";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const { data, live } = await api.dashboard();
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Manager Dashboard · マネージャー・ダッシュボード"
        title="Which deals are real — and which just look healthy?"
        lead="Deterministic deal-health, scored the same way for every rep. Red/yellow/green with a signal-by-signal reason, plus flags where a report's optimism quietly contradicts its data. No GPU, no black box."
      />
      <DashboardView initial={data} live={live} />
    </div>
  );
}
