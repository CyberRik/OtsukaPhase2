"use client";

import { useState } from "react";
import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RingiDraft } from "@/lib/types";

// Preset "business cards" the rep can attach — each carries a decision-maker
// title, which is exactly what clears the `missing_decision_maker` flag in the
// deterministic engine (senpai.health.scoring._has_decision_maker).
const DM_CONTACTS = [
  { value: "", ja: "— 決裁者を選択 —", en: "— pick a decision-maker —" },
  { value: "山田 太郎(情報システム部 部長)", ja: "山田 部長 · 情シス部長(決裁者)", en: "Bucho Yamada · IT Dept. Head (DM)" },
  { value: "佐藤 花子(取締役 経営企画)", ja: "佐藤 取締役 · 経営企画", en: "Director Sato · Corp. Planning" },
  { value: "鈴木 一郎(本部長 事業統括)", ja: "鈴木 本部長 · 事業統括", en: "Div. GM Suzuki · Business" },
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

/**
 * The Onboarding Dojo sandbox. The rep edits a follow-up daily report and
 * attaches the decision-maker's card, then re-runs the audit. The overlay is
 * session-scoped (built server-side, never persisted), so the seed data is
 * untouched — but the objections it resolves genuinely stop firing.
 */
export function SandboxCard({
  onApply, applying, lang,
}: {
  onApply: (draft: RingiDraft) => void;
  applying: boolean;
  lang: string;
}) {
  const ja = lang === "ja";
  const [contact, setContact] = useState("");
  const [report, setReport] = useState(
    ja
      ? "決裁者に同席いただき、現場のネットワークと運用ボリュームを確認。次回の意思決定事項と稟議スケジュールを合意した。"
      : "Met with the decision-maker on-site; confirmed the network and usage volume, and agreed the next decision items and the Ringi schedule.",
  );
  const [challenge, setChallenge] = useState(ja ? "現場調査に基づく最適構成の合意" : "Agreeing an optimal configuration from the site survey");

  const inputCls = "w-full rounded-lg border border-border bg-background px-2.5 py-1.5 font-jp text-[13px]";
  const canApply = (contact.trim() !== "" || report.trim() !== "") && !applying;

  return (
    <div className="rounded-2xl border border-primary/25 bg-primary/[0.03]">
      <div className="flex items-center gap-2 border-b border-primary/15 px-4 py-3">
        <Sparkles className="h-4 w-4 text-primary" />
        <div>
          <div className="text-[14px] font-bold text-foreground">
            {ja ? "オンボーディング道場 · サンドボックス" : "Onboarding Dojo · Sandbox"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {ja ? "日報を書き直し、決裁者に会って、もう一度稟議にかけよう。" : "Rewrite the report, meet the decision-maker, and re-run the Ringi."}
          </div>
        </div>
      </div>

      <div className="space-y-3 px-4 py-3">
        <Field label={ja ? "決裁者の名刺を添付" : "Attach decision-maker's card"}>
          <select value={contact} onChange={(e) => setContact(e.target.value)}
                  className="w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-[13px]">
            {DM_CONTACTS.map((c) => (
              <option key={c.value} value={c.value}>{ja ? c.ja : c.en}</option>
            ))}
          </select>
        </Field>
        <Field label={ja ? "追加の日報メモ(フォローアップ訪問)" : "New daily report note (follow-up visit)"}>
          <textarea value={report} onChange={(e) => setReport(e.target.value)} rows={3}
                    className={cn(inputCls, "leading-relaxed")} />
        </Field>
        <Field label={ja ? "把握した顧客課題" : "Customer challenge captured"}>
          <input value={challenge} onChange={(e) => setChallenge(e.target.value)} className={inputCls} />
        </Field>

        <div className="flex items-center justify-between pt-1">
          <p className="text-[11px] text-muted-foreground">
            {ja ? "※ シード情報は変更されません(セッション限定の上書き)" : "Seed data is never mutated (session-only overlay)."}
          </p>
          <button
            onClick={() => onApply({
              business_card_info: contact,
              daily_report: report,
              customer_challenge: challenge,
              activity_type: "002_Daily Report",
            })}
            disabled={!canApply}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            {applying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {ja ? "適用して再監査" : "Apply & re-run audit"}
          </button>
        </div>
      </div>
    </div>
  );
}
