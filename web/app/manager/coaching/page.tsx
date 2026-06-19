import { api } from "@/lib/api";
import { PageHeader } from "@/components/site/page-header";
import { ManagerCoaching } from "@/components/coaching/manager-coaching";

export const dynamic = "force-dynamic";

export default async function ManagerCoachingPage() {
  const { data } = await api.coaching();
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.coaching"
        titleKey="coaching.title"
        leadKey="coaching.lead"
      />
      <ManagerCoaching data={data} />
    </div>
  );
}
