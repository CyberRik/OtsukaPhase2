"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { AdminHeader, useFetched, Section } from "@/components/admin/kit";
import type { AdminRep, ManagerRef } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

export default function OrgPage() {
  const { data, live, refetch } = useFetched(api.adminOrg, { groups: [], unassigned: [], manager_pool: [] });
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const reassign = async (employeeId: string, managerId: string) => {
    if (!managerId) return;
    setBusy(employeeId);
    setNote(null);
    const res = await api.adminReassign(employeeId, managerId);
    setBusy(null);
    if (res.data.rep) {
      setNote(`Moved ${res.data.rep.name} → ${res.data.rep.manager_name}`);
      refetch();
    } else {
      setNote("Reassignment failed (see server).");
    }
  };

  const RepRow = ({ rep }: { rep: AdminRep }) => (
    <div className="flex items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1.5">
      <span className="font-mono text-[11px] text-muted-foreground">{rep.employee_id}</span>
      <span className="text-[13px] font-medium text-foreground">{rep.name}</span>
      <span className="text-[11px] text-muted-foreground">{rep.role}</span>
      <span className="ml-auto text-[11px] text-muted-foreground">{rep.open_deals} open</span>
      <select
        aria-label={`Reassign ${rep.name}`}
        defaultValue=""
        disabled={busy === rep.employee_id}
        onChange={(e) => reassign(rep.employee_id, e.target.value)}
        className="rounded-md border border-border bg-card px-1.5 py-1 text-[11.5px] text-muted-foreground outline-none focus:border-primary disabled:opacity-50"
      >
        <option value="">move to…</option>
        {data.manager_pool
          .filter((m: ManagerRef) => m.employee_id !== rep.reports_to && m.employee_id !== rep.employee_id)
          .map((m: ManagerRef) => (
            <option key={m.employee_id} value={m.employee_id}>{m.name} ({m.employee_id})</option>
          ))}
      </select>
    </div>
  );

  return (
    <div className="space-y-4">
      <AdminHeader
        title="Org & Assignments"
        lead="Which salesperson reports to which manager. Use the dropdown on any person to move them — it rewrites reports_to on the spot."
        live={live}
      >
        {note && <span className="rounded-md bg-band-green/10 px-2 py-1 text-[11.5px] text-band-green">{note}</span>}
      </AdminHeader>

      <div className="grid gap-3 lg:grid-cols-2">
        {data.groups.map((g) => (
          <Section
            key={g.manager.employee_id}
            title={`${g.manager.name} · ${g.manager.role}`}
            right={<span className="text-[11px] text-muted-foreground">{g.team.length} report(s)</span>}
          >
            <div className="space-y-1.5">
              {g.team.length === 0 && <div className="text-[12px] text-muted-foreground">No direct reports.</div>}
              {g.team.map((rep) => <RepRow key={rep.employee_id} rep={rep} />)}
            </div>
          </Section>
        ))}
      </div>

      {data.unassigned.length > 0 && (
        <Section title="Unassigned" right={<span className={cn("text-[11px]", "text-band-yellow")}>{data.unassigned.length} without a manager</span>}>
          <div className="grid gap-1.5 md:grid-cols-2">
            {data.unassigned.map((rep) => <RepRow key={rep.employee_id} rep={rep} />)}
          </div>
        </Section>
      )}
    </div>
  );
}
