"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Lightbulb, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export default function ManagerIngestionPage() {
  const { t } = useT();
  const [statement, setStatement] = useState("");
  const [situation, setSituation] = useState("");
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<string>("");
  const [error, setError] = useState("");

  const inputCls = "w-full rounded-lg border border-border bg-background px-3 py-2 font-jp text-[13.5px]";

  async function submit() {
    if (!statement.trim()) { setError(t("mingest.statementRequired")); return; }
    setSaving(true); setError(""); setSavedId("");
    const { data, live } = await api.addPrinciple({
      statement: statement.trim(),
      situation: situation.trim(),
      tags: tags.split(",").map((s) => s.trim()).filter(Boolean),
    });
    setSaving(false);
    if (live && data?.principle) {
      setSavedId(data.principle.principle_id);
      setStatement(""); setSituation(""); setTags("");
    } else {
      setError(t("mingest.saveFailed"));
    }
  }

  return (
    <div className="space-y-7">
      <header className="space-y-2">
        <div className="eyebrow text-navy">{t("nav.mingestion")}</div>
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight md:text-[28px]">{t("mingest.title")}</h1>
        <p className="max-w-2xl text-[14px] leading-relaxed text-muted-foreground">{t("mingest.lead")}</p>
      </header>

      {savedId && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-conf-high/30 bg-conf-high/5 px-4 py-3 text-[13px] text-conf-high">
          <Check className="h-4 w-4" /> {t("mingest.saved")}
          <span className="font-mono text-[11px] opacity-70">{savedId}</span>
          <Link href="/manager/knowledge" className="ml-auto inline-flex items-center gap-1 font-medium text-navy hover:underline">
            {t("common.viewAll")} <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-band-red/30 bg-band-red/5 px-4 py-3 text-[13px] text-band-red">{error}</div>
      )}

      <div className="rounded-xl border border-border bg-card">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <Lightbulb className="h-4 w-4 text-navy" />
          <span className="text-[13px] font-semibold text-foreground">{t("mingest.title")}</span>
        </div>
        <div className="space-y-3.5 px-4 py-4">
          <Field label={t("mingest.statement")}>
            <textarea
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              rows={3}
              placeholder={t("mingest.statementPh")}
              className={`${inputCls} leading-relaxed`}
            />
          </Field>
          <Field label={t("mingest.situation")}>
            <textarea
              value={situation}
              onChange={(e) => setSituation(e.target.value)}
              rows={2}
              placeholder={t("mingest.situationPh")}
              className={`${inputCls} leading-relaxed`}
            />
          </Field>
          <Field label={t("mingest.tags")}>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder={t("mingest.tagsPh")}
              className={inputCls}
            />
          </Field>
          <div className="flex justify-end pt-1">
            <button
              onClick={submit}
              disabled={saving || !statement.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-navy px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-navy/90 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Lightbulb className="h-3.5 w-3.5" />}
              {t("mingest.submit")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
