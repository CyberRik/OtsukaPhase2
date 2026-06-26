// Offline fallback so the UI is demo-proof even with no API running (and so a
// static Vercel preview renders). The knowledge data here is the REAL cited
// interview-derived data; the deal slice is a representative sample of the
// deterministic engine's output. When the API is reachable, live data wins.

import type {
  CoachingWorkspace,
  CoachResponse,
  DashboardData,
  GrowthResponse,
  KnowledgeItem,
  Principle,
  RepProfileRow,
  Source,
} from "./types";

export const COACHING_FALLBACK: CoachingWorkspace = {
  needs_coaching: [
    { deal_id: "D023", rep: "佐藤美咲", employee_id: "R02", customer: "有限会社村田印刷", issue: "confidence_mismatch", priority: "high", params: { rank: "2_A+" }, band: "red", score: 70, n_issues: 3 },
    { deal_id: "D014", rep: "伊藤翔", employee_id: "R05", customer: "山田電機", issue: "confidence_mismatch", priority: "high", params: { rank: "3_A" }, band: "red", score: 65, n_issues: 2 },
    { deal_id: "D031", rep: "渡辺さくら", employee_id: "R06", customer: "株式会社小林製作所", issue: "missing_decision_maker", priority: "high", params: { reports: 3 }, band: "red", score: 55, n_issues: 2 },
    { deal_id: "D008", rep: "山本健一", employee_id: "R07", customer: "大和産業", issue: "long_inactivity", priority: "high", params: { days: 47 }, band: "red", score: 50, n_issues: 2 },
    { deal_id: "D019", rep: "中村優子", employee_id: "R08", customer: "東和システム", issue: "premature_discount", priority: "medium", params: { rate: 18 }, band: "yellow", score: 35, n_issues: 1 },
    { deal_id: "D027", rep: "鈴木大輔", employee_id: "R03", customer: "北川物産", issue: "weak_customer_discovery", priority: "medium", params: { filled: 1, total: 4 }, band: "yellow", score: 30, n_issues: 1 },
  ],
  trends: [
    { issue: "incomplete_reports", count: 12, trend: "flat", reps: ["佐藤美咲", "伊藤翔", "高橋由美", "渡辺さくら", "山本健一", "中村優子"] },
    { issue: "missing_decision_maker", count: 8, trend: "flat", reps: ["伊藤翔", "高橋由美", "渡辺さくら", "中村優子"] },
    { issue: "repeated_unresolved", count: 8, trend: "up", reps: ["佐藤美咲", "高橋由美", "山本健一", "中村優子"] },
    { issue: "confidence_mismatch", count: 4, trend: "flat", reps: ["佐藤美咲", "伊藤翔", "高橋由美"] },
    { issue: "long_inactivity", count: 4, trend: "flat", reps: ["伊藤翔", "山本健一", "中村優子"] },
    { issue: "premature_discount", count: 3, trend: "up", reps: ["中村優子", "鈴木大輔", "山本健一"] },
  ],
  confidence: [
    { deal_id: "D023", rep: "佐藤美咲", customer: "有限会社村田印刷", confidence: "high", band: "red", score: 70, status: "mismatch", positives: 1, signals: [{ key: "quote", positive: false }, { key: "decision_maker", positive: false }, { key: "recent_activity", positive: true }] },
    { deal_id: "D014", rep: "伊藤翔", customer: "山田電機", confidence: "high", band: "red", score: 65, status: "mismatch", positives: 0, signals: [{ key: "quote", positive: false }, { key: "decision_maker", positive: false }, { key: "recent_activity", positive: false }] },
    { deal_id: "D031", rep: "渡辺さくら", customer: "株式会社小林製作所", confidence: "high", band: "red", score: 55, status: "mismatch", positives: 1, signals: [{ key: "quote", positive: true }, { key: "decision_maker", positive: false }, { key: "recent_activity", positive: false }] },
    { deal_id: "D040", rep: "田中健太", customer: "富士産業", confidence: "high", band: "green", score: 10, status: "supported", positives: 3, signals: [{ key: "quote", positive: true }, { key: "decision_maker", positive: true }, { key: "recent_activity", positive: true }] },
    { deal_id: "D012", rep: "高橋由美", customer: "松田サービス", confidence: "moderate", band: "yellow", score: 25, status: "supported", positives: 2, signals: [{ key: "quote", positive: true }, { key: "decision_maker", positive: false }, { key: "recent_activity", positive: true }] },
  ],
  summary: { reps_need_coaching: 7, opportunities_flagged: 20, top_issue: "incomplete_reports", improving: 0 },
};

// Team rollup fallback for the 1:1 Rep Profiles section (worst-needing-coaching
// first). Per-rep profile/progress/threads fall back to null/[] when offline.
export const REP_PROFILES_FALLBACK: RepProfileRow[] = [
  { employee_id: "R05", name: "伊藤翔", role: "新人営業", open_deals: 9, at_risk: 5, avg_risk: 48, development_focus: "missing_decision_maker", n_weaknesses: 4, acted_on_rate: 0.33 },
  { employee_id: "R06", name: "渡辺さくら", role: "新人営業", open_deals: 8, at_risk: 4, avg_risk: 42, development_focus: "weak_customer_discovery", n_weaknesses: 3, acted_on_rate: 0.5 },
  { employee_id: "R02", name: "佐藤美咲", role: "営業", open_deals: 11, at_risk: 4, avg_risk: 39, development_focus: "confidence_mismatch", n_weaknesses: 3, acted_on_rate: 0.6 },
  { employee_id: "R08", name: "中村優子", role: "新人営業", open_deals: 7, at_risk: 3, avg_risk: 35, development_focus: "premature_discount", n_weaknesses: 2, acted_on_rate: null },
  { employee_id: "R07", name: "山本健一", role: "営業", open_deals: 10, at_risk: 3, avg_risk: 33, development_focus: "long_inactivity", n_weaknesses: 2, acted_on_rate: 0.5 },
];

export const GROWTH_FALLBACK: GrowthResponse = {
  growth: {
    rep: { employee_id: "R05", name: "伊藤翔", role: "junior", department: "第一営業部", specialty_tags: ["複合機"] },
    totals: { reviews: 10, principles: 3, scenarios: 7, streak_weeks: 7 },
    this_month: { label: "2026-06", reviews: 2, new_principles: 2, active_days: 3, strengths: 3 },
    skills: [
      { key: "relationship_building", stars: 4, trend: "flat", evidence: [], insight: "5件の担当案件で平均4.2回の接触" },
      { key: "decision_maker_discovery", stars: 3, trend: "improving", evidence: [], insight: "強いランク案件3件中2件で決裁者を特定" },
      { key: "customer_discovery", stars: 5, trend: "flat", evidence: [], insight: "12件の活動中11件で顧客課題を記録 (92%)" },
      { key: "closing_discipline", stars: 4, trend: "flat", evidence: [], insight: "クローズ済み2件中2件受注" },
      { key: "proposal_pricing", stars: 3, trend: "needs_work", evidence: [], insight: "5件中2件で見積を発行" },
    ],
    monthly: [
      { month: "2026-01", count: 0, skill_scores: {} },
      { month: "2026-02", count: 0, skill_scores: {} },
      { month: "2026-03", count: 1, skill_scores: { customer_discovery: 0.8, relationship_building: 0.4 } },
      { month: "2026-04", count: 4, skill_scores: { customer_discovery: 0.75, relationship_building: 0.5, decision_maker_discovery: 0.3 } },
      { month: "2026-05", count: 15, skill_scores: { customer_discovery: 0.9, relationship_building: 0.7, decision_maker_discovery: 0.5, proposal_pricing: 0.4 } },
      { month: "2026-06", count: 3, skill_scores: { customer_discovery: 1.0, relationship_building: 0.6, decision_maker_discovery: 0.67 } },
    ],
  },
  juniors: [
    { employee_id: "R05", name: "伊藤翔" },
    { employee_id: "R06", name: "渡辺さくら" },
    { employee_id: "R07", name: "山本健一" },
  ],
};

export const COACH_SECTIONS = [
  { key: "observations", ja: "経験豊富な営業が気づくこと", en: "What a senior notices", icon: "eye" },
  { key: "missing_info", ja: "確認できていない情報", en: "Missing information", icon: "search" },
  { key: "risks", ja: "リスクの兆候", en: "Risk signals", icon: "alert" },
  { key: "questions", ja: "次に聞くとよい質問", en: "Questions to ask next", icon: "message" },
  { key: "next_actions", ja: "取りうる次の一手", en: "Possible next moves", icon: "route" },
  { key: "decision_factors", ja: "判断に影響する要因", en: "What should drive the choice", icon: "scale" },
];

export const TEACH_NOTE =
  "正解を一つ示すものではありません。先輩なら何に注目するか、その思考の型を提示します。状況に応じて自分で選んでください。";

export const COACH_EXAMPLES = [
  {
    title: "前向きだが決裁者が不明",
    deal_id: "D001",
    note: "担当者は前向きで『ほぼ決まり』との感触。受注確度は高いと見ている。ただ決裁者にはまだ会えていない。",
    hint: "高い確度が案件の実態・決裁者の状況と噛み合っているか",
  },
  {
    title: "競合と比較中",
    deal_id: "D021",
    note: "競合製品と比較中。価格が高いと言われ、見積は提示済み。次回までに再提案する予定。",
    hint: "価格勝負に流される前に差別化軸を考える",
  },
  {
    title: "初回訪問・IT環境を確認",
    deal_id: "D016",
    note: "初回訪問。先方のPC環境とネットワーク構成を一通り確認できた。担当者は忙しそうだった。",
    hint: "情報収集に走り、関係構築と決裁者の把握が後回しに",
  },
  {
    title: "部長は前向き",
    deal_id: "D008",
    note: "部長は前向きで好感触。現場のIT担当にはまだ会えていない。",
    hint: "決裁者の感触だけで成約間近と判断していないか",
  },
];

export const COACH_FALLBACK: CoachResponse = {
  teach_note: TEACH_NOTE,
  sections: COACH_SECTIONS,
  used_deal: false,
  result: {
    observations: [
      "誰が最終的に決めるのか(決裁者)が見えていない",
      "次の打ち合わせや意思決定の時期が決まっていない",
      "何を基準に判断されるのかが分かっていない",
      "次の具体的な一歩(誰が・何を)が決まっていない",
      "予算の有無・規模が確認できていない",
      "停滞を示す言葉「検討します」が出ている",
    ],
    missing_info: ["決裁者・意思決定に関わる人", "次回接触日・意思決定の時期", "意思決定の判断基準", "次の具体的アクションと担当", "予算の所在と規模"],
    risks: [
      "決裁ルートが不明なまま進むと、終盤で想定外の関与者が出て止まりやすい",
      "期日がないと『検討します』のまま自然消滅しやすい",
      "顧客の言葉に停滞サインがある。受け身で待つと流れやすい",
    ],
    questions: [
      "この件はどなたが最終的にご決定されますか？他に関わる方はいますか？",
      "社内でのご検討はいつ頃まとまりそうですか？次にお話しする日を今決めておけますか？",
      "ご判断にあたって特に重視される点はどこですか？(価格/サポート/実績 など)",
    ],
    next_actions: [
      "その場で次回の打ち合わせ日を仮押さえし、案件を宙に浮かせない",
      "現場担当に『最終決定はどなたと進めますか』と決裁プロセスを確認する",
      "先輩の知見(出典 I01・I02 / 確度high): 御社の業務で今いちばんお困りのことは何ですか？",
    ],
    decision_factors: [
      "決裁者が誰で、何を重視するか(コスト/安心/現場負担)",
      "顧客の導入希望時期と予算サイクル(年度末など)",
      "顧客が重視する価値(価格 vs 安心 vs 実績)",
    ],
  },
};

export const DASHBOARD_FALLBACK: DashboardData = {
  today: "2026-06-16",
  kpis: {
    open_deals: 49,
    at_risk: 5,
    watch: 20,
    healthy: 24,
    flagged_reports: 70,
    pipeline_total: 32321000,
  },
  reps: ["佐藤", "鈴木", "高橋", "田中", "渡辺", "伊藤"],
  deals: [
    { deal_id: "D001", customer: "株式会社アクメ商事", customer_id: "C01", rep: "鈴木", stage: "proposal", amount: 450000, band: "red", chip: "🔴", score: 100, days_stale: 67, close_date: "2026-05-27", slips: 2, n_flags: 5, decision_maker_identified: false, rep_close_likelihood: "high" },
    { deal_id: "D014", customer: "山田製作所", customer_id: "C14", rep: "高橋", stage: "negotiation", amount: 1280000, band: "red", chip: "🔴", score: 80, days_stale: 41, close_date: "2026-06-02", slips: 1, n_flags: 3, decision_maker_identified: false, rep_close_likelihood: "high" },
    { deal_id: "D023", customer: "みどり物産", customer_id: "C23", rep: "田中", stage: "closing", amount: 720000, band: "red", chip: "🔴", score: 65, days_stale: 38, close_date: "2026-06-10", slips: 1, n_flags: 2, decision_maker_identified: true, rep_close_likelihood: "medium" },
    { deal_id: "D007", customer: "大和テック", customer_id: "C07", rep: "佐藤", stage: "proposal", amount: 340000, band: "yellow", chip: "🟡", score: 45, days_stale: 22, close_date: "2026-07-01", slips: 0, n_flags: 1, decision_maker_identified: false, rep_close_likelihood: "medium" },
    { deal_id: "D031", customer: "北野エンジニアリング", customer_id: "C31", rep: "渡辺", stage: "qualified", amount: 210000, band: "yellow", chip: "🟡", score: 35, days_stale: 18, close_date: "2026-07-15", slips: 0, n_flags: 1, decision_maker_identified: false, rep_close_likelihood: "low" },
    { deal_id: "D018", customer: "セントラル工業", customer_id: "C18", rep: "伊藤", stage: "negotiation", amount: 980000, band: "yellow", chip: "🟡", score: 30, days_stale: 12, close_date: "2026-07-08", slips: 0, n_flags: 0, decision_maker_identified: true, rep_close_likelihood: "medium" },
    { deal_id: "D004", customer: "光通信サービス", customer_id: "C04", rep: "佐藤", stage: "proposal", amount: 560000, band: "green", chip: "🟢", score: 15, days_stale: 5, close_date: "2026-07-20", slips: 0, n_flags: 0, decision_maker_identified: true, rep_close_likelihood: "medium" },
    { deal_id: "D012", customer: "丸三フーズ", customer_id: "C12", rep: "鈴木", stage: "closing", amount: 430000, band: "green", chip: "🟢", score: 10, days_stale: 3, close_date: "2026-06-25", slips: 0, n_flags: 0, decision_maker_identified: true, rep_close_likelihood: "high" },
  ],
  flags: [
    { deal_id: "D001", customer: "株式会社アクメ商事", rep: "鈴木", severity: "high", flag: "optimism_mismatch", message: "担当の見込みは『高』だが健全度は赤" },
    { deal_id: "D001", customer: "株式会社アクメ商事", rep: "鈴木", severity: "high", flag: "close_date_passed", message: "完了予定日(2026-05-27)を過ぎても案件がオープン" },
    { deal_id: "D014", customer: "山田製作所", rep: "高橋", severity: "high", flag: "stale_active", message: "41日連絡がないままアクティブ扱い" },
    { deal_id: "D023", customer: "みどり物産", rep: "田中", severity: "medium", flag: "missing_fields", message: "必須項目が未入力: 次アクション" },
    { deal_id: "D007", customer: "大和テック", rep: "佐藤", severity: "low", flag: "unsupported_stage", message: "proposal段階への移行を裏づけるメモがない" },
  ],
};

export const SOURCES_FALLBACK: Source[] = [
  { source_id: "I01", kind: "interview", participant_role: "senior", date: "2026-06", uri: "transcripts/respondent_A.md", notes: "回答者A。7つの二者択一シナリオに対しA/B選択と理由を回答。" },
  { source_id: "I02", kind: "interview", participant_role: "senior", date: "2026-06", uri: "transcripts/respondent_B.md", notes: "回答者B。同一7シナリオに回答。状況依存の判断を明示。" },
  { source_id: "Q01", kind: "instrument", participant_role: "n/a", date: "2026-06", uri: "surveys/questionnaire.md", notes: "共通の質問票。開放型10問+二者択一7シナリオ。" },
];

export const PRINCIPLES_FALLBACK: Principle[] = [
  { principle_id: "P001", statement: "新しい提案や別の情報提供で間口を広げる前に、今進行中の案件の確度と決定時期を確認して白黒つける。", tags: ["クロージング", "案件管理", "決定先延ばし"], status: "approved", interview_ids: ["I01", "I02"], n_interviews: 2, support: [{ source_id: "I01", quote: "別の情報提供を始めるのであれば、今の案件を白黒つけてからやるべきだと考えているから", location: "Q1" }, { source_id: "I02", quote: "決定時期、案件確度を正確に把握したいため、状況確認のため電話で確認する。", location: "Q1" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P006", statement: "決裁者(部長)は社内のIT担当者が納得しないと契約に踏み切らない。現場の技術担当の納得を取り付けることが決裁の前提条件。", tags: ["決裁者未特定", "ステークホルダー", "提案"], status: "approved", interview_ids: ["I01", "I02"], n_interviews: 2, support: [{ source_id: "I01", quote: "部長の性格にもよるが、IT担当者に納得していただけないと部長は気持ちよく契約に踏み切ってもらえないと考えているから", location: "Q4" }, { source_id: "I02", quote: "IT部門の方の意見を無視して商談を進めることになり今後の取引に支障が出るリスクがあるため。", location: "Q4" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P008", statement: "初回訪問は情報収集より関係構築を優先する。いきなり環境やスペックを聞いても引き出せないため、業務内容・関心事のヒアリングから入る。", tags: ["初回訪問", "ヒアリング", "関係構築"], status: "approved", interview_ids: ["I01", "I02"], n_interviews: 2, support: [{ source_id: "I01", quote: "初回訪問のお客様にただ環境を聞くだけでは教えてもらえない可能性が高いと考えているから", location: "Q5" }, { source_id: "I02", quote: "初回訪問では、お客様との関係構築が最重要と考えており、資料ベースではなく、お客様の業務内容や興味・関心事項をヒアリングしたいため。", location: "Q5" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P011", statement: "決裁者同席の依頼はタイミングと関係性で判断する。信頼が築けていない段階で急に依頼すると相手が「蔑ろにされた」と感じ逆効果。関係が良ければ早めに、そうでなければ段階を踏む。", tags: ["決裁者同席", "クロージング", "関係構築"], status: "approved", interview_ids: ["I01", "I02"], n_interviews: 2, support: [{ source_id: "I01", quote: "今まで商談をしていた相手に、いきなり次回は決裁者の同席を依頼すると、気分を害される可能性があると考えるから", location: "Q7" }, { source_id: "I02", quote: "商談相手との関係性によると思います。仲が良く、お願いできる関係性であればAを選択。…そうでない場合には、商談相手が「自分を蔑ろにされた」とならないように、Bの選択をして慎重に進めるべきだと思います。", location: "Q7" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P002", statement: "値引きの提示は最終手段。安易に価格を下げるカードを切らない。", tags: ["価格", "交渉"], status: "candidate", interview_ids: ["I01"], n_interviews: 1, support: [{ source_id: "I01", quote: "値段を下げるプランを提示するのは最終手段だと考えているから", location: "Q2" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P003", statement: "担当者の「〜になるかもしれない」という曖昧な情報だけで方針を決めず、キーマンに会って状況を確認してから動く。", tags: ["決裁者未特定", "情報確認", "決定先延ばし"], status: "candidate", interview_ids: ["I02"], n_interviews: 1, support: [{ source_id: "I02", quote: "担当者が「～になるかもしれない」と言っているので、情報が定かではないため出方を決めきれません。キーマンと商談をし、状況確認してから…", location: "Q2" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P004", statement: "最初から妥協策を出さず、まず本命の手(A)を試し、通らなければ次善策(B)に切り替える段階的アプローチをとる。", tags: ["交渉", "クロージング"], status: "candidate", interview_ids: ["I01"], n_interviews: 1, support: [{ source_id: "I01", quote: "まずはAを試みて、だめならBに切り替えると思います。", location: "Q3" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P005", statement: "予算の確保が案件進行の前提。資金の目処が立っていなければ早期クロージングを押さず、まず予算化を支援する。", tags: ["予算", "クロージング"], status: "candidate", interview_ids: ["I02"], n_interviews: 1, support: [{ source_id: "I02", quote: "基本的にはお客様側でお金が用意できていないと案件が進まないのでB。", location: "Q3" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P007", statement: "専門的なミーティングを設定する前段階で、移行作業の負荷を下げる提案を決裁者に行い、技術部門の負担懸念を先回りで解消する。", tags: ["ステークホルダー", "移行", "提案"], status: "candidate", interview_ids: ["I02"], n_interviews: 1, support: [{ source_id: "I02", quote: "専門的なミーティングをセッティングするよりも前段階で、移行作業の負荷を下げるための提案を提案決裁者へすると思います。", location: "Q4" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P009", statement: "競合を貶めない。他社を下げる発言は逆効果になるため、自社の価値で勝負する。", tags: ["競合", "差別化"], status: "candidate", interview_ids: ["I01"], n_interviews: 1, support: [{ source_id: "I01", quote: "他社を下げる発言は、逆効果につながると思っているから", location: "Q6" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
  { principle_id: "P010", statement: "最終的に契約先を決めるのはお客様。選定基準を先に確認し、その基準に合ったアプローチで自社の価値を示す。", tags: ["差別化", "ヒアリング", "競合"], status: "candidate", interview_ids: ["I02"], n_interviews: 1, support: [{ source_id: "I02", quote: "最終的に決めるのはお客様のため、お客様が契約先を選ぶ判断基準を確認してから…", location: "Q6" }], corroborating_surveys: [], added_by: "extraction", added_at: "2026-06-18T00:00:00Z" },
];

export const ITEMS_FALLBACK: KnowledgeItem[] = [
  { item_id: "G0001", scenario: "新人が初回訪問で、開口一番「PCは何台ですか？OSは？ネットワークは？」と環境ヒアリングを始めた。担当者の口は重く、具体的な情報をほとんど引き出せないまま時間が過ぎた。", signals: ["担当者の反応が浅く、口が重い", "環境やスペックの質問に具体的な答えが返ってこない", "お客様との関係がまだ築けていない"], questions: ["御社の業務で今いちばんお困りのことは何ですか？", "普段どんな場面でPCやネットワークをお使いですか？", "（環境を直接うかがう前に）まず関心事をお聞きしてもよいですか？"], risks: ["初回から情報収集に走ると警戒され、以降の関係構築が難しくなる", "環境情報が不正確なまま提案に進んでしまう"], alternatives: ["既に信頼関係のある再訪問で時間が限られる場合は、環境確認を先に進めてよいこともある", "技術案件で要件が急ぐ場合は、要点だけ先に押さえる選択もある"], tags: ["初回訪問", "ヒアリング", "関係構築"], provenance: { principle_id: "P008", interview_ids: ["I01", "I02"], generator_model: "human-curated", prompt_version: "kx-v1", generated_at: "2026-06-18T00:00:00Z", grounding_passed: true, grounding_notes: "原則P008から導出。新規の助言・数値なし。代替視点あり。" }, review: { status: "approved", reviewer: "akiyama", reviewed_at: "2026-06-18T00:00:00Z", notes: "2名一致の原則。原則どおりで承認。" }, confidence: "high", principle_statement: "初回訪問は情報収集より関係構築を優先する。", n_interviews: 2 },
  { item_id: "G0002", scenario: "商談を何度か重ねてきた担当者に、新人が次回の打ち合わせで「部長にもご同席いただけますか」といきなり依頼したところ、担当者の表情が曇った。", signals: ["担当者との信頼関係がまだ浅い", "担当者を飛ばして決裁者に行こうとしている印象を与えている", "同席依頼の理由が相手に伝わっていない"], questions: ["この案件、最終的にはどなたとお決めになりますか？", "次回のお打ち合わせを、部長にもメリットをお伝えできる場にできますか？", "（関係が良ければ）工数を抑えるため、一度ご同席をお願いできますか？"], risks: ["急な決裁者同席依頼で担当者が『蔑ろにされた』と感じ、逆効果になる", "逆に慎重になりすぎると決裁が遅れ、案件が停滞する"], alternatives: ["仲が良くお願いできる関係なら、早めに同席を依頼して決定までの工数を減らすのが有効", "関係が浅い場合は段階を踏み、担当者を立ててから同席を打診する"], tags: ["決裁者同席", "クロージング", "関係構築"], provenance: { principle_id: "P011", interview_ids: ["I01", "I02"], generator_model: "human-curated", prompt_version: "kx-v1", generated_at: "2026-06-18T00:00:00Z", grounding_passed: true, grounding_notes: "原則P011から導出。両回答者の分岐をalternativesに反映。" }, review: { status: "approved", reviewer: "akiyama", reviewed_at: "2026-06-18T00:00:00Z", notes: "2名一致。状況依存の判断を代替視点に明示。承認。" }, confidence: "high", principle_statement: "決裁者同席の依頼はタイミングと関係性で判断する。", n_interviews: 2 },
  { item_id: "G0003", scenario: "既存顧客から別商材に興味があると言われ、新人がさっそくその提案準備を始めた。だが今進行中の複合機案件は「社内で検討します」のままで、決定時期も確度も曖昧だった。", signals: ["進行中案件の決定時期が未確認", "案件確度が曖昧なまま放置されている", "新しい提案に気を取られ、今の案件が前に進んでいない"], questions: ["今の複合機案件、ご決定はいつ頃の見込みでしょうか？", "社内でのご検討は今どの段階まで進んでいますか？", "（新提案に入る前に）まず今の案件を一歩前に進めてよいですか？"], risks: ["複数案件に手を広げ、どれも中途半端になって決まらない", "既存案件が宙に浮いたまま自然消滅・失注する"], alternatives: ["既存案件の確度が高く、相手からの要望が強ければ並行して新提案を進めてよい", "別商材が今の案件のクロージングを後押しするなら、あえて一緒に提案する手もある"], tags: ["クロージング", "案件管理", "決定先延ばし"], provenance: { principle_id: "P001", interview_ids: ["I01", "I02"], generator_model: "human-curated", prompt_version: "kx-v1", generated_at: "2026-06-18T00:00:00Z", grounding_passed: true, grounding_notes: "原則P001から導出。確度・決定時期の確認を軸に。" }, review: { status: "approved", reviewer: "akiyama", reviewed_at: "2026-06-18T00:00:00Z", notes: "2名一致の原則。承認。" }, confidence: "high", principle_statement: "新しい提案で間口を広げる前に、今の案件の確度と決定時期を確認して白黒つける。", n_interviews: 2 },
  { item_id: "G0004", scenario: "部長が前向きで「ほぼ決まり」と言われ、新人は成約間近と日報に書いた。しかし現場のIT担当者からは具体的な質問も懸念もまだ出ていない。", signals: ["現場IT担当者の納得が確認できていない", "部長の感触だけで成約間近と判断している", "技術面の懸念が未解消の可能性がある"], questions: ["IT担当の方は今回の構成にご納得いただけていますか？", "現場で気になっている点や不安はありませんか？", "部長とIT担当、それぞれにメリットをお伝えできていますか？"], risks: ["IT担当者が納得しておらず、最後に部長が契約に踏み切れない", "技術部門を軽視し、今後の取引に支障が出る"], alternatives: ["IT担当者が既に強く推している場合は、決裁者の最終承認に注力してよい", "小規模で技術論点が薄い案件なら、決裁者中心に進める判断もある"], tags: ["決裁者未特定", "ステークホルダー", "提案"], provenance: { principle_id: "P006", interview_ids: ["I01", "I02"], generator_model: "human-curated", prompt_version: "kx-v1", generated_at: "2026-06-18T00:00:00Z", grounding_passed: true, grounding_notes: "原則P006から導出。現場IT担当者の納得を軸に。" }, review: { status: "approved", reviewer: "akiyama", reviewed_at: "2026-06-18T00:00:00Z", notes: "2名一致(R1-Q4 + R2-Q4)。承認。" }, confidence: "high", principle_statement: "決裁者は社内のIT担当者が納得しないと契約に踏み切らない。", n_interviews: 2 },
];
