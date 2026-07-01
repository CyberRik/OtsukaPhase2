import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { PageHeader } from "@/components/site/page-header";
import { GrowthDashboard } from "@/components/growth/growth-dashboard";

export const dynamic = "force-dynamic";

export default async function JuniorGrowthPage() {
  const { data: growthData } = await api.growth(await currentEmployeeId());
  const repId = growthData.growth.rep.employee_id;
  const repName = growthData.growth.rep.name;

  const [{ data: threadsData }, { data: dashData }] = await Promise.all([
    api.coachThreads({ repId }),
    api.dashboard(repName),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.reports"
        titleKey="growth.title"
        leadKey="growth.lead"
      />
      <GrowthDashboard
        initial={growthData}
        threads={threadsData.threads}
        deals={dashData.deals}
      />
    </div>
  );
}
