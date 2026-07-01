"use client";

import { Users } from "lucide-react";
import { useT } from "@/lib/i18n";
import { repText } from "@/lib/content-i18n";

type TeamRep = { employee_id: string; name: string; role: string; open_deals: number };

// "My team" — every rep on the logged-in manager's team (coachees + assigned
// juniors), including newly-assigned juniors with no deals yet. Rendered above
// the coaching workspace so an assignment is visible immediately.
export function TeamRoster({ reps }: { reps: TeamRep[] }) {
  const { t, lang } = useT();
  if (!reps.length) return null;
  return (
    <section className="rounded-2xl border border-border bg-card p-5">
      <div className="mb-3 flex items-center gap-2 text-[13px] font-medium text-foreground">
        <Users className="h-4 w-4 text-primary" /> {t("team.title")}
        <span className="text-muted-foreground">({reps.length})</span>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2">
        {reps.map((r) => (
          <li
            key={r.employee_id}
            className="flex items-center justify-between rounded-lg border border-border bg-muted/30 px-3 py-2"
          >
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium text-foreground">
                {repText(lang, r.name).text}
              </div>
              <div className="text-[11px] text-muted-foreground">{r.employee_id} · {r.role}</div>
            </div>
            <div className="shrink-0 text-[11px] text-muted-foreground">
              {r.open_deals > 0 ? t("team.openDeals", { n: r.open_deals }) : t("team.noDeals")}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
