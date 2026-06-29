"use client";

import { useState } from "react";
import { Check, Lightbulb, Loader2, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Principle } from "@/lib/types";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

/**
 * Manager-only "add a principle" authoring, lifted out of the old standalone
 * /manager/ingestion page into a dialog beside the Knowledge corpus it feeds.
 * On success the new candidate principle is handed to the explorer via onAdded.
 */
export function AddPrincipleDialog({ onAdded }: { onAdded: (p: Principle) => void }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [statement, setStatement] = useState("");
  const [situation, setSituation] = useState("");
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const inputCls = "w-full rounded-lg border border-border bg-background px-3 py-2 font-jp text-[13.5px]";

  function reset() {
    setStatement(""); setSituation(""); setTags(""); setError(""); setSaved(false);
  }

  async function submit() {
    if (!statement.trim()) { setError(t("mingest.statementRequired")); return; }
    setSaving(true); setError(""); setSaved(false);
    const { data, live } = await api.addPrinciple({
      statement: statement.trim(),
      situation: situation.trim(),
      tags: tags.split(",").map((s) => s.trim()).filter(Boolean),
    });
    setSaving(false);
    if (live && data?.principle) {
      onAdded(data.principle);
      // Clear the inputs for a possible next entry, then show the confirmation.
      setStatement(""); setSituation(""); setTags(""); setError("");
      setSaved(true);
    } else {
      setError(t("mingest.saveFailed"));
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) reset(); }}>
      <DialogTrigger asChild>
        <button className="inline-flex items-center gap-1.5 rounded-lg border border-navy/30 bg-navy/10 px-2.5 py-1.5 text-[12px] font-medium text-navy transition-colors hover:bg-navy/20">
          <Plus className="h-3.5 w-3.5" /> {t("knowledge.addPrinciple")}
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogTitle className="flex items-center gap-2 text-[15px]">
          <Lightbulb className="h-4 w-4 text-navy" /> {t("mingest.title")}
        </DialogTitle>
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">{t("mingest.lead")}</p>

        {saved && (
          <div className="flex items-center gap-2 rounded-lg border border-conf-high/30 bg-conf-high/5 px-3 py-2 text-[12.5px] text-conf-high">
            <Check className="h-3.5 w-3.5" /> {t("mingest.saved")}
          </div>
        )}
        {error && (
          <div className="rounded-lg border border-band-red/30 bg-band-red/5 px-3 py-2 text-[12.5px] text-band-red">{error}</div>
        )}

        <div className="space-y-3.5">
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
      </DialogContent>
    </Dialog>
  );
}
