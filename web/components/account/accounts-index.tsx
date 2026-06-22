"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Building2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Band, DealRow } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { formatYen } from "@/lib/utils";
import { BandDot } from "@/components/band";
import { Skeleton } from "@/components/ui/skeleton";

type AccountRow = {
  customer_id: string;
  customer: string;
  open_deals: number;
  pipeline: number;
  worst: Band;
};

const BAND_ORDER: Record<Band, number> = { red: 0, yellow: 1, green: 2 };

// Discoverability surface: roll the open-deal pipeline up by customer so a user
// can browse active accounts and drill into each one's Account Intelligence.
// Derived entirely from the existing dashboard (no extra backend).
function rollUp(deals: DealRow[]): AccountRow[] {
  const by = new Map<string, AccountRow>();
  for (const d of deals) {
    const cur = by.get(d.customer_id) ?? {
      customer_id: d.customer_id, customer: d.customer, open_deals: 0, pipeline: 0, worst: "green" as Band,
    };
    cur.open_deals += 1;
    cur.pipeline += d.amount;
    if (BAND_ORDER[d.band] < BAND_ORDER[cur.worst]) cur.worst = d.band;
    by.set(d.customer_id, cur);
  }
  return [...by.values()].sort((a, b) => b.pipeline - a.pipeline);
}

export function AccountsIndex({ role }: { role: "junior" | "manager" }) {
  const { t, lang } = useT();
  const [rows, setRows] = useState<AccountRow[] | null>(null);

  useEffect(() => {
    let alive = true;
    api.dashboard().then(({ data }) => { if (alive) setRows(rollUp(data.deals)); });
    return () => { alive = false; };
  }, []);

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">{t("nav.accounts")}</h1>
        <p className="text-[13.5px] text-muted-foreground">
          {lang === "ja"
            ? "アクティブなアカウントを選ぶと、関係性全体の健全度・トレンド・拡大機会・シニア所見が見られます。"
            : "Pick an active account to see its whole-relationship health, trajectory, expansion opportunities and a senior read."}
        </p>
      </header>

      {!rows ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14 w-full" />)}</div>
      ) : (
        <div className="grid gap-2.5 sm:grid-cols-2">
          {rows.map((r) => (
            <Link
              key={r.customer_id}
              href={`/${role}/accounts/${r.customer_id}`}
              className="group flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 transition-colors hover:border-primary/40 hover:bg-primary/[0.02]"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate font-jp text-[14px] font-medium text-foreground">{r.customer}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2.5 text-[11.5px] text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><BandDot band={r.worst} /> {r.open_deals} {lang === "ja" ? "件進行中" : "open"}</span>
                  <span className="font-mono">{formatYen(r.pipeline)}</span>
                </div>
              </div>
              <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
