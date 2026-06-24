import { api } from "@/lib/api";
import { PageHeader } from "@/components/site/page-header";
import { ManagerCoaching } from "@/components/coaching/manager-coaching";
import { RepProfiles } from "@/components/coaching/rep-profiles";

export const dynamic = "force-dynamic";

export default async function ManagerCoachingPage() {
  const [{ data }, { data: profiles }] = await Promise.all([
    api.coaching(),
    api.repProfiles(),
  ]);
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.coaching"
        titleKey="coaching.title"
        leadKey="coaching.lead"
      />
      <ManagerCoaching data={data} />
      <RepProfiles initial={profiles.reps} />
    </div>
  );
}
