import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { PageHeader } from "@/components/site/page-header";
import { ManagerDashboard } from "@/components/manager/manager-dashboard";

export const dynamic = "force-dynamic";

// Overview-first home: the full-width team dashboard (Overview / All deals /
// Flags), scoped to the logged-in manager's coachees. The Copilot is its own
// tab; "Ask the Copilot" on a deal jumps there pre-grounded.
export default async function ManagerHomePage() {
  const { data, live } = await api.dashboard(undefined, await currentEmployeeId());
  return (
    <div className="space-y-8">
      <PageHeader eyebrowKey="nav.home" titleKey="dash.title" leadKey="dash.lead" />
      <ManagerDashboard dashboard={data} live={live} />
    </div>
  );
}
