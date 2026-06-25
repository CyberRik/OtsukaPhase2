"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, FileUp, Loader2, Save, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { ActivityDraft, DealRow, GrowthData } from "@/lib/types";

// Activity-type vocabulary (SPR sales_activities.activity_type). Lifted from the
// old in-chat capture draft — data ingestion now lives on this dedicated page.
const ACTIVITY_TYPES = [
  "001_Scheduled", "002_Daily Report", "003_Deal", "004_Quote",
  "005_Order", "006_Maintenance Quote", "007_Maintenance Contract",
  "008_Contract Billing", "901_Auto-Scheduled",
] as const;

type Customer = { customer_id: string; name: string };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export default function JuniorIngestionPage() {
  const { t } = useT();
  const fileRef = useRef<HTMLInputElement>(null);

  const [deals, setDeals] = useState<DealRow[]>([]);
  const [employeeId, setEmployeeId] = useState<string>("");
  const [fileName, setFileName] = useState<string>("");
  const [extracting, setExtracting] = useState(false);
  const [mock, setMock] = useState(false);
  const [draft, setDraft] = useState<ActivityDraft | null>(null);
  const [customerId, setCustomerId] = useState<string>("");
  const [dealId, setDealId] = useState<string>("");
  const [resolveNote, setResolveNote] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    Promise.all([api.dashboard(), api.growth()]).then(([db, gr]) => {
      setDeals(db.data.deals);
      setEmployeeId(gr.data.growth.rep.employee_id);
    });
  }, []);

  // Unique customers, derived from the rep's pipeline deals (the picker options).
  const customers = useMemo<Customer[]>(() => {
    const seen = new Map<string, string>();
    for (const d of deals) if (!seen.has(d.customer_id)) seen.set(d.customer_id, d.customer);
    return [...seen.entries()].map(([customer_id, name]) => ({ customer_id, name }));
  }, [deals]);

  const dealsForCustomer = useMemo(
    () => deals.filter((d) => d.customer_id === customerId),
    [deals, customerId],
  );

  const set = (k: keyof ActivityDraft, v: string) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const inputCls = "w-full rounded-lg border border-border bg-background px-2.5 py-1.5 font-jp text-[13px]";

  async function onFile(file: File) {
    setExtracting(true);
    setError(""); setSaved(false);
    setFileName(file.name);
    let payload: { audio?: File; image?: File; text?: string };
    if (file.type.startsWith("audio")) payload = { audio: file };
    else if (file.type.startsWith("image")) payload = { image: file };
    else payload = { text: await file.text() };
    const { data, live } = await api.ingest(payload);
    setExtracting(false);
    if (!data) { setError(t("ingest.extractFailed")); return; }
    setDraft(data.draft);
    setMock(live && !data.multimodal);
    // Auto-resolve the customer named in the extracted text; pre-select on a
    // confident single match, otherwise leave the picker for the rep to choose.
    const res = await api.smartResolveCustomer(data.raw_text);
    if (res.data.status === "resolved" && res.data.customer?.customer_id) {
      setCustomerId(res.data.customer.customer_id);
      setResolveNote(t("ingest.resolved", { name: res.data.customer.name ?? "" }));
    } else if (res.data.status === "ambiguous") {
      setResolveNote(t("ingest.ambiguous"));
    } else {
      setResolveNote(t("ingest.notFound"));
    }
  }

  async function onSave() {
    if (!draft || !customerId || !dealId || !employeeId) return;
    setSaving(true); setError("");
    const { data, live } = await api.saveActivity({
      draft, customer_id: customerId, deal_id: dealId, employee_id: employeeId,
    });
    setSaving(false);
    if (live && data?.saved) {
      setSaved(true);
      // Reset for the next report, but keep the customer/deal selection handy.
      setDraft(null); setFileName(""); setResolveNote("");
    } else {
      setError(t("ingest.saveFailed"));
    }
  }

  const canSave = !!draft && !!customerId && !!dealId && !saving;

  return (
    <div className="space-y-7">
      <header className="space-y-2">
        <div className="eyebrow text-primary">{t("nav.ingestion")}</div>
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight md:text-[28px]">{t("ingest.title")}</h1>
        <p className="max-w-2xl text-[14px] leading-relaxed text-muted-foreground">{t("ingest.lead")}</p>
      </header>

      {/* Upload */}
      <input
        ref={fileRef}
        type="file"
        accept="audio/*,image/*,text/*,.txt,.md,.csv"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }}
      />
      <button
        onClick={() => fileRef.current?.click()}
        disabled={extracting}
        className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-card px-4 py-6 text-[13px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-60"
      >
        {extracting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
        {extracting ? t("ingest.extracting") : t("ingest.upload")}
      </button>

      {saved && (
        <div className="flex items-center gap-2 rounded-xl border border-conf-high/30 bg-conf-high/5 px-4 py-3 text-[13px] text-conf-high">
          <Check className="h-4 w-4" /> {t("ingest.saved")}
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-band-red/30 bg-band-red/5 px-4 py-3 text-[13px] text-band-red">{error}</div>
      )}

      {/* Draft form */}
      {draft && (
        <div className="rounded-xl border border-border bg-card">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
            <FileUp className="h-4 w-4 text-navy" />
            <span className="text-[13px] font-semibold text-foreground">{t("ingest.review")}</span>
            {fileName && <span className="font-mono text-[10px] text-muted-foreground">{fileName}</span>}
            {mock && (
              <span className="rounded-full border border-band-yellow/30 bg-band-yellow/10 px-2 py-0.5 text-[10px] font-medium text-band-yellow">
                {t("capture.mock")}
              </span>
            )}
          </div>

          <div className="space-y-3 px-4 py-3">
            {/* Destination: customer + deal binding */}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("ingest.customer")}>
                <select
                  value={customerId}
                  onChange={(e) => { setCustomerId(e.target.value); setDealId(""); }}
                  className="w-full rounded-lg border border-border bg-background px-2.5 py-1.5 font-jp text-[13px]"
                >
                  <option value="">{t("ingest.pickCustomer")}</option>
                  {customers.map((c) => <option key={c.customer_id} value={c.customer_id}>{c.name}</option>)}
                </select>
              </Field>
              <Field label={t("ingest.deal")}>
                <select
                  value={dealId}
                  onChange={(e) => setDealId(e.target.value)}
                  disabled={!customerId}
                  className="w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-[13px] disabled:opacity-50"
                >
                  <option value="">{t("ingest.pickDeal")}</option>
                  {dealsForCustomer.map((d) => (
                    <option key={d.deal_id} value={d.deal_id}>{d.deal_id} · {d.stage}</option>
                  ))}
                </select>
              </Field>
            </div>
            {resolveNote && <p className="text-[11px] text-muted-foreground">{resolveNote}</p>}

            <Field label={t("capture.field.type")}>
              <select
                value={draft.activity_type}
                onChange={(e) => set("activity_type", e.target.value)}
                className="w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-[13px]"
              >
                {ACTIVITY_TYPES.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </Field>
            <Field label={t("capture.field.report")}>
              <textarea
                value={draft.daily_report}
                onChange={(e) => set("daily_report", e.target.value)}
                rows={4}
                className={cn(inputCls, "leading-relaxed")}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("capture.field.contact")}>
                <input value={draft.business_card_info} onChange={(e) => set("business_card_info", e.target.value)} className={inputCls} />
              </Field>
              <Field label={t("capture.field.category")}>
                <input value={draft.product_major_category} onChange={(e) => set("product_major_category", e.target.value)} className={inputCls} />
              </Field>
            </div>
            <Field label={t("capture.field.challenge")}>
              <input value={draft.customer_challenge} onChange={(e) => set("customer_challenge", e.target.value)} className={inputCls} />
            </Field>

            <div className="flex items-center justify-between pt-1">
              <p className="text-[11px] text-muted-foreground">{t("ingest.hint")}</p>
              <button
                onClick={onSave}
                disabled={!canSave}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                {t("ingest.save")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
