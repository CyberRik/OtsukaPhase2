// Mirrors the JSON shapes returned by senpai/api/server.py. Keep in sync with
// the FastAPI handlers — these are the contract between backend and frontend.

export type Band = "red" | "yellow" | "green";
export type Confidence = "high" | "medium" | "low" | "unverified";
export type ItemStatus = "draft" | "approved" | "needs_edit" | "rejected";

export interface DealRow {
  deal_id: string;
  customer: string;
  customer_id: string;
  rep: string;
  stage: string;
  amount: number;
  band: Band;
  chip: string;
  score: number;
  days_stale: number | null;
  close_date: string;
  slips: number;
  n_flags: number;
  decision_maker_identified: boolean;
  rep_close_likelihood: string | null;
}

export interface FlagRow {
  deal_id: string;
  customer: string;
  rep: string;
  severity: "high" | "medium" | "low";
  flag: string;
  message: string;
}

export interface DashboardKpis {
  open_deals: number;
  at_risk: number;
  watch: number;
  healthy: number;
  flagged_reports: number;
  pipeline_total: number;
}

export interface DashboardData {
  today: string;
  kpis: DashboardKpis;
  deals: DealRow[];
  flags: FlagRow[];
  reps: string[];
}

export interface Signal {
  name: string;
  points: number;
  reason: string;
}

export interface DealNote {
  note_id: string;
  date: string;
  channel: string;
  text: string;
}

export interface DealDetail {
  deal: {
    deal_id: string;
    customer: string;
    customer_id: string;
    rep: string;
    stage: string;
    amount: number;
    expected_close_date: string | null;
    last_contact_date: string | null;
    decision_maker_identified: boolean;
    rep_close_likelihood: string | null;
    close_date_history: string[];
    stage_history: { stage: string; entered_date: string }[];
    products: string[];
  };
  score: number;
  band: Band;
  signals: Signal[];
  flags: { name: string; severity: string; message: string }[];
  notes: DealNote[];
  timeline: TimelineEvent[];
  report: Record<string, unknown> | null;
}

export interface TimelineEvent {
  date: string;
  kind: "activity" | "quote" | "order" | "gap";
  type: string;
  title: string;
  detail: string;
  amount: number | null;
  days?: number;
}

export interface SimilarCase {
  deal_id: string;
  customer: string;
  product_category: string;
  amount: number;
  outcome: "won" | "lost";
  theme: string;
  principle_ids: string[];
  decision_maker: boolean;
  discounted: boolean;
  n_activities: number;
}

// --- Account Intelligence (mirrors senpai/account/*.to_dict) ----------------
export interface AccountHealthDimension {
  name: string;
  points: number;
  max: number;
  reason: string;
}

export interface AccountHealth {
  score: number;
  band: Band;
  dimensions: AccountHealthDimension[];
}

export interface AccountPattern {
  id: string;
  label_ja: string;
  label_en: string;
  evidence: string;
  polarity: "positive" | "risk" | "neutral";
}

// Expansion opportunities (kind set) and positive trajectory patterns share the
// expansion_signals array, so the type is a permissive union of both shapes.
export interface AccountSignal {
  kind?: "cross_sell" | "upsell" | "growth";
  target?: string;
  rationale?: string;
  evidence?: string;
  confidence?: "low" | "medium" | "high";
  id?: string;
  label_ja?: string;
  label_en?: string;
  polarity?: "positive" | "risk" | "neutral";
}

export interface AccountQuote {
  quote_id: string;
  amount: number;
  product: string | null;
  discount_rate: number | null;
  quoted_at: string | null;
  order_flag: string | null;
}

export interface AccountOrder {
  order_id: string;
  amount: number;
  product: string | null;
  ordered_at: string | null;
}

export interface AccountSummary {
  customer_id: string;
  customer: string;
  industry: string;
  size: string;
  active_deals: number;
  won_deals: number;
  lost_deals: number;
  total_pipeline: number;
  historical_revenue: number;
  activity_trend: string;
  last_activity: string | null;
  recent_quotes: AccountQuote[];
  recent_orders: AccountOrder[];
  environment: string | null;
  health: AccountHealth;
  risk_signals: AccountPattern[];
  expansion_signals: AccountSignal[];
  recommended_focus: string;
}

export interface CoachSectionMeta {
  key: string;
  ja: string;
  en: string;
  icon: string;
}

export interface CoachResponse {
  teach_note: string;
  sections: CoachSectionMeta[];
  used_deal: boolean;
  result: Record<string, string[]>;
  narration?: string | null;
  llm_model?: string | null;
  explanations?: Explanation[];
  account_context?: {
    account_profile?: {
      name: string;
      industry?: string;
      environment_constraints?: string;
    };
    deterministic_imperatives?: string[];
    applicable_principles?: string[];
    historical_success_reference?: any[];
  } | null;
}

export interface CoachExample {
  title: string;
  note: string;
  hint: string;
  deal_id?: string;   // seed examples are anchored to a real deal for grounding
}

export interface Citation {
  source_id: string;
  quote: string;
  location: string;
}

export interface Principle {
  principle_id: string;
  statement: string;
  tags: string[];
  status: string;
  interview_ids: string[];
  n_interviews: number;
  support: Citation[];
  corroborating_surveys: Citation[];
  added_by: string;
  added_at: string;
}

// --- Manager knowledge ingestion (`POST /api/knowledge/principles`) --------
export interface AddPrincipleRequest {
  statement: string;
  situation?: string;
  tags?: string[];
  added_by?: string;
}

export interface Provenance {
  principle_id: string;
  interview_ids: string[];
  generator_model: string;
  prompt_version: string;
  generated_at: string;
  grounding_passed: boolean;
  grounding_notes: string;
}

export interface Review {
  status: ItemStatus;
  reviewer: string;
  reviewed_at: string;
  notes: string;
}

export interface KnowledgeItem {
  item_id: string;
  scenario: string;
  signals: string[];
  questions: string[];
  risks: string[];
  alternatives: string[];
  tags: string[];
  provenance: Provenance;
  review: Review;
  confidence: Confidence;
  principle_statement: string;
  n_interviews: number;
}

export interface CoachingCardItem {
  deal_id: string;
  rep: string;
  employee_id: string;
  customer: string;
  issue: string;
  priority: "high" | "medium" | "low";
  params: Record<string, string | number>;
  band: Band;
  score: number;
  n_issues: number;
  explanation?: Explanation;
}

export interface CoachingTrend {
  issue: string;
  count: number;
  trend: "up" | "down" | "flat";
  reps: string[];
}

export interface ConfVRSignal {
  key: string;
  positive: boolean;
}

export interface ConfVRItem {
  deal_id: string;
  rep: string;
  customer: string;
  confidence: "high" | "moderate" | "low";
  band: Band;
  score: number;
  status: "mismatch" | "supported";
  positives: number;
  signals: ConfVRSignal[];
}

export interface CoachingSummary {
  reps_need_coaching: number;
  opportunities_flagged: number;
  top_issue: string | null;
  improving: number;
}

export interface CoachingWorkspace {
  needs_coaching: CoachingCardItem[];
  trends: CoachingTrend[];
  confidence: ConfVRItem[];
  summary: CoachingSummary;
}

// --- Per-rep 1:1 coaching (rep-profiles / rep-profile / rep-progress / threads)
// Mirrors senpai/api/server.py:/api/coach/rep-profile{,s}, /rep-progress, /threads
// and the dicts in senpai/coach/profile.py + progress.py.

/** One compact row in the team rollup (`/api/coach/rep-profiles` → `reps[]`). */
export interface RepProfileRow {
  employee_id: string;
  name: string;
  role: string;
  open_deals: number;
  at_risk: number;
  avg_risk: number;
  development_focus: string | null; // issue key (translate via coaching.issue.*)
  n_weaknesses: number;
  acted_on_rate: number | null;
}

export interface RepWeakness {
  issue: string;
  label: string; // backend-provided Japanese label
  count: number;
  share: number;
  example_deals: string[];
  principle: { id: string; statement: string; approved: boolean } | null;
  case:
    | { deal_id: string; customer: string; outcome: string; product_category?: string; principle_ids?: string[] }
    | null;
  action: string; // backend-provided Japanese coaching action
}

export interface RepThreadSummary {
  total: number;
  open: number;
  acknowledged: number;
  resolved: number;
  acted_on_rate: number | null;
}

/** Full 1:1 profile (`/api/coach/rep-profile/{id}`). */
export interface RepProfile {
  employee_id: string;
  name: string;
  role: string;
  open_deals: number;
  at_risk: number;
  avg_risk: number;
  band_mix: { red: number; yellow: number; green: number };
  development_focus: string | null;
  focus_explanation: Explanation | null;
  weaknesses: RepWeakness[];
  strengths: string[];
  talking_points: string[];
  threads: RepThreadSummary;
}

export interface RepProgressWindow {
  window: string; // e.g. "FY2025"
  active_deals: number;
  weaknesses_per_deal: number;
  by_issue: Record<string, number>;
}

/** Longitudinal progress (`/api/coach/rep-progress/{id}`). */
export interface RepProgress {
  employee_id: string;
  name: string;
  windows: string[];
  series: RepProgressWindow[];
  trends: Record<string, "improving" | "worsening" | "flat">;
  headline: string; // backend-provided Japanese headline
  coaching_acted_on: { total: number; resolved: number; rate: number | null };
}

export interface CoachingThreadMessage {
  role: "manager" | "rep";
  author_id: string;
  date: string;
  text: string;
}

/** Manager↔rep coaching thread (`/api/coach/threads`). */
export interface CoachingThread {
  thread_id: string;
  deal_id: string;
  employee_id: string;
  manager_id: string;
  issue_key: string;
  created_at: string;
  status: "open" | "acknowledged" | "resolved";
  messages: CoachingThreadMessage[];
}

// --- Multimodal ingestion (`POST /api/ingest`) -----------------------------
// Editable draft matching the sales_activities schema. See
// senpai/ingestion/multimodal.py:ActivityExtraction.
export interface ActivityDraft {
  activity_type: string;
  business_card_info: string;
  product_major_category: string;
  customer_challenge: string;
  daily_report: string;
}

export interface IngestResult {
  raw_text: string;
  draft: ActivityDraft;
  multimodal: boolean; // false → server used deterministic mock extraction (offline)
}

// --- Attachment → chat context (`POST /api/extract`) -----------------------
// Plain text only — no structured extraction. The workspace chat attaches this
// as context and asks the assistant about it.
export interface ExtractResult {
  raw_text: string;
}

// --- Persist a reviewed daily report (`POST /api/ingest/save`) -------------
export interface SaveActivityRequest {
  draft: ActivityDraft;
  customer_id: string;
  deal_id: string;
  employee_id: string;
}

export interface SaveActivityResult {
  saved: boolean;
  activity: Record<string, unknown> | null;
}

export interface GrowthSkill {
  key: string;
  stars: number;
}

export interface GrowthMonth {
  month: string;
  count: number;
}

export interface GrowthData {
  rep: { employee_id: string; name: string; role: string; department: string; specialty_tags: string[] };
  totals: { reviews: number; principles: number; scenarios: number; streak_weeks: number };
  this_month: { label: string; reviews: number; new_principles: number; active_days: number; strengths: number };
  skills: GrowthSkill[];
  monthly: GrowthMonth[];
}

export interface GrowthResponse {
  growth: GrowthData;
  juniors: { employee_id: string; name: string }[];
}

export interface Source {
  source_id: string;
  kind: string;
  participant_role: string;
  date: string;
  uri: string;
  notes: string;
}

// --- Coaching Explainability ------------------------------------------------
export interface TriggerCondition {
  rule_id: string;
  rule_type: "lens" | "signal" | "flag" | "issue" | "presence";
  description: string;
  description_en: string;
  matched_data: Record<string, unknown>;
}

export interface EvidenceItem {
  field: string;
  value: string;
  interpretation: string;
  interpretation_en: string;
}

export interface ExplSimilarCase {
  deal_id: string;
  customer: string;
  outcome: "won" | "lost";
  relevance: string;
  relevance_en: string;
  principle_ids: string[];
  lesson: string;
}

export interface OutcomeStats {
  total_similar: number;
  won: number;
  lost: number;
  loss_rate: number;
  conditions_desc: string;
  conditions_desc_en: string;
}

export interface Explanation {
  recommendation_id: string;
  recommendation_text: string;
  triggers: TriggerCondition[];
  evidence: EvidenceItem[];
  similar_cases: ExplSimilarCase[];
  outcome_stats: OutcomeStats | null;
  confidence: "high" | "medium" | "low";
  principle_id: string | null;
  principle_statement: string | null;
}
