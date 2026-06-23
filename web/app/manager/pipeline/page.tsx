import { api } from "@/lib/api";
import { PageHeader } from "@/components/site/page-header";
import { DashboardView } from "@/components/dashboard/dashboard-view";

export const dynamic = "force-dynamic";

export default async function ManagerPipelinePage() {
  const { data, live } = await api.dashboard();
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.pipeline"
        titleKey="pipeline.title"
        leadKey="pipeline.lead"
      />
      <DashboardView initial={data} live={live} view="pipeline" />
    </div>
  );
}
