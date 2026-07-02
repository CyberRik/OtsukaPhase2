"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { AdminHeader, useFetched, fmt } from "@/components/admin/kit";
import { cn } from "@/lib/utils";

export default function PeoplePage() {
  const { data, live } = useFetched(api.adminReps, { reps: [], managers: [] });
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | "manager" | "junior">("all");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return data.reps.filter((r) => {
      if (roleFilter === "manager" && !r.is_manager) return false;
      if (roleFilter === "junior" && r.role !== "junior") return false;
      if (!needle) return true;
      return [r.employee_id, r.name, r.department, r.division, r.manager_name]
        .some((v) => (v || "").toLowerCase().includes(needle));
    });
  }, [data.reps, q, roleFilter]);

  return (
    <div className="space-y-4">
      <AdminHeader title="People" lead="Everyone registered as a salesperson or manager, and whether they have a login." live={live} />

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name, id, department, manager…"
          className="w-72 rounded-lg border border-border bg-background px-3 py-1.5 text-[13px] outline-none focus:border-primary"
        />
        <div className="flex gap-1">
          {(["all", "manager", "junior"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setRoleFilter(f)}
              className={cn(
                "rounded-md px-2.5 py-1.5 text-[12px] font-medium capitalize transition-colors",
                roleFilter === f ? "bg-primary text-primary-foreground" : "border border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {f}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[12px] text-muted-foreground">{fmt(rows.length)} people</span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-card shadow-card">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2 font-medium">ID</th>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Department</th>
              <th className="px-3 py-2 font-medium">Manager</th>
              <th className="px-3 py-2 font-medium text-right">Team</th>
              <th className="px-3 py-2 font-medium text-right">Open deals</th>
              <th className="px-3 py-2 font-medium text-center">Login</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.employee_id} className="border-b border-border/50 last:border-0 hover:bg-muted/40">
                <td className="px-3 py-2 font-mono text-[12px] text-muted-foreground">{r.employee_id}</td>
                <td className="px-3 py-2 font-medium text-foreground">
                  {r.name}
                  {r.is_top_performer && <span className="ml-1.5 text-[10px] text-band-yellow">★</span>}
                </td>
                <td className="px-3 py-2">
                  <span className={cn(
                    "rounded-full px-1.5 py-0.5 text-[10.5px] font-medium",
                    r.is_manager ? "bg-navy/10 text-navy" : "bg-primary/10 text-primary",
                  )}>{r.role}</span>
                </td>
                <td className="px-3 py-2 text-muted-foreground">{r.department} {r.division}</td>
                <td className="px-3 py-2 text-muted-foreground">{r.manager_name || "—"}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.is_manager ? r.team_size : "—"}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.open_deals}</td>
                <td className="px-3 py-2 text-center">
                  {r.has_account ? <span className="text-band-green">●</span> : <span className="text-muted-foreground/40">○</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
