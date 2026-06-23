import { api } from "@/lib/api";
import { PageHeader } from "@/components/site/page-header";
import { GrowthDashboard } from "@/components/growth/growth-dashboard";

export const dynamic = "force-dynamic";

export default async function JuniorGrowthPage() {
  const { data } = await api.growth();
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.reports"
        titleKey="growth.title"
        leadKey="growth.lead"
      />
      <GrowthDashboard initial={data} />
    </div>
  );
}
