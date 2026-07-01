import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { PageHeader } from "@/components/site/page-header";
import { ManagerCoaching } from "@/components/coaching/manager-coaching";
import { TeamRoster } from "@/components/coaching/team-roster";

export const dynamic = "force-dynamic";

export default async function ManagerCoachingPage() {
  const mgr = await currentEmployeeId();
  const [{ data }, { data: profiles }, { data: team }] = await Promise.all([
    api.coaching(mgr),
    api.repProfiles(mgr),
    api.coachTeam(mgr),
  ]);
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.coaching"
        titleKey="coaching.title"
        leadKey="coaching.lead"
      />
      <TeamRoster reps={team.reps} />
      <ManagerCoaching data={data} profiles={profiles.reps} />
    </div>
  );
}
