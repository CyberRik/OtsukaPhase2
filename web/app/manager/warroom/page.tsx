import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { PageHeader } from "@/components/site/page-header";
import { WarRoom } from "@/components/warroom/war-room";

export const dynamic = "force-dynamic";

// Pipeline War Room — the Analytics pillar. A deterministic time-machine replay
// of the manager's whole pipeline: every deal reconstructed and re-scored as of
// weekly snapshot dates by the same health engine the dashboard uses.
export default async function WarRoomPage() {
  const { data, live } = await api.warroom(await currentEmployeeId());
  return (
    <div className="space-y-8">
      <PageHeader eyebrowKey="nav.warroom" titleKey="warroom.title" leadKey="warroom.lead" />
      <WarRoom data={data} live={live} />
    </div>
  );
}
