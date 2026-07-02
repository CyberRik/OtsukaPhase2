"use client";

import { api } from "@/lib/api";
import { AdminHeader, useFetched } from "@/components/admin/kit";
import type { AdminActivityEvent } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

export default function ActivityPage() {
  const { data, live } = useFetched(api.adminActivity, { events: [] });

  // group by day
  const byDay = new Map<string, AdminActivityEvent[]>();
  for (const e of data.events) {
    const day = e.date || "—";
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day)!.push(e);
  }

  return (
    <div className="space-y-4">
      <AdminHeader title="Activity" lead="Recent system activity: coaching-thread messages and daily reports, newest first." live={live} />

      <div className="space-y-4">
        {[...byDay.entries()].map(([day, events]) => (
          <div key={day}>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{day}</div>
            <div className="space-y-1.5">
              {events.map((e, i) => (
                <div key={i} className="flex items-start gap-2.5 rounded-lg border border-border bg-card px-3 py-2 shadow-card">
                  <span className={cn(
                    "mt-0.5 shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                    e.type === "coaching" ? "bg-navy/10 text-navy" : "bg-primary/10 text-primary",
                  )}>
                    {e.type === "coaching" ? "coaching" : "report"}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[11.5px] text-muted-foreground">
                      <span className="font-mono">{e.rep}</span>
                      {e.manager && <> · mgr <span className="font-mono">{e.manager}</span></>}
                      {e.deal && <> · deal <span className="font-mono">{e.deal}</span></>}
                    </div>
                    <div className="truncate text-[13px] text-foreground">{e.text || "—"}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
        {data.events.length === 0 && <div className="text-[13px] text-muted-foreground">No activity recorded.</div>}
      </div>
    </div>
  );
}
