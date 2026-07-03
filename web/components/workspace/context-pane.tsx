"use client";

import { useMemo, useState } from "react";
import { Building2, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useWorkspaceFocus } from "@/lib/chat-store";
import { customerText } from "@/lib/content-i18n";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { BandPill } from "@/components/band";
import { AccountView } from "@/components/account/account-view";
import type { Role } from "@/lib/session";
import type { Band, DealRow, GrowthData } from "@/lib/types";

// Surface the most urgent work first: at-risk deals before watch before healthy.
const BAND_ORDER: Record<Band, number> = { red: 0, yellow: 1, green: 2 };

/**
 * The left pane of the Command Center: the rep's live deal/account context.
 * Clicking a deal sets the shared workspace focus, which the Copilot (right
 * pane) reads to ground its next answer — no slash commands, no retyping a
 * customer name. "Open account" reuses the existing AccountView in a drawer, so
 * the full account read sits beside the conversation instead of on its own page.
 */
export function ContextPane({
  deals,
  role,
  profile,
}: {
  deals: DealRow[];
  role: Role;
  // Junior passes its growth profile; the manager surface has no single-rep
  // profile, so this is optional. Currently informational only.
  profile?: GrowthData;
}) {
  const { t, lang } = useT();
  const { focus, setFocus } = useWorkspaceFocus(role);
  const [q, setQ] = useState("");
  const [openAccount, setOpenAccount] = useState<{ id: string; name: string } | null>(null);

  const myDeals = useMemo(() => {
    const query = q.trim().toLowerCase();
    return deals
      .filter((d) => {
        if (!query) return true;
        const name = customerText(lang, d.customer).text.toLowerCase();
        return name.includes(query) || d.customer.toLowerCase().includes(query);
      })
      .slice()
      .sort((a, b) => BAND_ORDER[a.band] - BAND_ORDER[b.band] || b.amount - a.amount);
  }, [deals, q, lang]);

  return (
    <div className="space-y-4">

      <div>
        <div className="eyebrow">{t("cc.todayWork")}</div>
        <p className="mt-1 text-[12px] text-muted-foreground">{t("cc.todayWorkLead")}</p>
      </div>

      <label className="flex items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 py-2">
        <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("cc.searchAccounts")}
          className="w-full bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
        />
      </label>

      <div className="space-y-2">
        {myDeals.length === 0 && (
          <p className="px-1 py-6 text-center text-[12.5px] text-muted-foreground">{t("cc.noDeals")}</p>
        )}
        {myDeals.map((d) => {
          const name = customerText(lang, d.customer).text;
          const active = focus.dealId === d.deal_id;
          return (
            <Card
              key={d.deal_id}
              role="button"
              tabIndex={0}
              onClick={() => setFocus({ dealId: d.deal_id, customerId: d.customer_id, customerName: name })}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setFocus({ dealId: d.deal_id, customerId: d.customer_id, customerName: name });
                }
              }}
              className={cn(
                "cursor-pointer transition-colors",
                active ? "ring-2 ring-primary/40" : "hover:border-primary/40",
              )}
            >
              <CardContent className="flex items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] font-medium">{name}</div>
                  <div className="truncate text-[11.5px] text-muted-foreground">
                    {d.stage} · ¥{d.amount.toLocaleString("ja-JP")}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <BandPill band={d.band} />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenAccount({ id: d.customer_id, name });
                    }}
                    className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-primary hover:bg-primary/5"
                  >
                    <Building2 className="h-3 w-3" />
                    {t("cc.openAccount")}
                  </button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Full account read — the existing AccountView, now in a drawer beside the
          Copilot rather than on its own route. */}
      <Dialog open={!!openAccount} onOpenChange={(o) => !o && setOpenAccount(null)}>
        <DialogContent className="p-5">
          <DialogTitle className="sr-only">{openAccount?.name ?? t("cc.openAccount")}</DialogTitle>
          {openAccount && (
            <AccountView
              customerId={openAccount.id}
              role={role}
              compact
              onAskCopilot={() => {
                // Hand off to the Copilot grounded on this account's most urgent
                // open deal (falling back to the account itself), then close.
                const top = deals
                  .filter((d) => d.customer_id === openAccount.id)
                  .sort((a, b) => BAND_ORDER[a.band] - BAND_ORDER[b.band] || b.amount - a.amount)[0];
                setFocus(
                  top
                    ? { dealId: top.deal_id, customerId: openAccount.id, customerName: openAccount.name }
                    : { customerId: openAccount.id, customerName: openAccount.name },
                );
                setOpenAccount(null);
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
