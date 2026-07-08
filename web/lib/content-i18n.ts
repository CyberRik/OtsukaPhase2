// ---------------------------------------------------------------------------
// Content localization for Japanese *knowledge data* (principles, derived
// coaching items, source notes, tags). The chrome dictionary lives in i18n.tsx;
// this file translates the real business knowledge the platform teaches.
//
// Rule of thumb:
//   - Teachable knowledge (principles, derived items, tags, corpus notes) IS
//     translated here so an English audience gets a 100%-English screen.
//   - Verbatim interview quotes (Principle.support, corroborating_surveys) are
//     SOURCE MATERIAL and intentionally stay Japanese — translating a citation
//     would defeat its purpose as evidence. Those carry their own context.
//
// Fallback contract: if an English translation is missing, callers fall back to
// the Japanese original and surface a small "JP Original" badge so the screen is
// honest about what the reader is seeing.
// ---------------------------------------------------------------------------

import type { Lang } from "./i18n";

// --- Principle statements (P001–P011) --------------------------------------
export const PRINCIPLE_EN: Record<string, string> = {
  P001:
    "Before widening the conversation with a new proposal or extra information, pin down the certainty and decision timing of the deal already in progress and get a clear yes or no.",
  P002: "Offering a discount is a last resort. Don't play the price-cut card too easily.",
  P003:
    "Don't set your approach on a contact's vague “it might turn out this way.” Meet the key decision-maker and confirm the situation before acting.",
  P004:
    "Don't lead with a compromise. Try your first-choice move (A) first, and switch to the fallback (B) only if it doesn't land — a staged approach.",
  P005:
    "Securing budget is a precondition for the deal to move. If funding isn't in sight, don't push for an early close — help the customer get it budgeted first.",
  P006:
    "The decision-maker (the department head) won't commit to a contract until the in-house IT staff are convinced. Winning over the technical staff on the ground is a precondition for approval.",
  P007:
    "Before setting up a technical meeting, propose ways to reduce the migration workload to the decision-maker, heading off the technical team's workload concerns in advance.",
  P008:
    "On a first visit, prioritize building the relationship over gathering information. Asking about systems or specs up front rarely draws answers, so start by listening to the customer's work and concerns.",
  P009:
    "Don't disparage competitors. Talking down other companies backfires, so compete on your own value.",
  P010:
    "The customer is the one who ultimately chooses the vendor. Confirm their selection criteria first, then show your value in a way that fits those criteria.",
  P011:
    "Judge a request for the decision-maker to attend by timing and relationship. Asking abruptly before trust is built makes the contact feel sidelined and backfires. If the relationship is strong, ask early; if not, move step by step.",
};

// --- Tags ------------------------------------------------------------------
export const TAG_EN: Record<string, string> = {
  "クロージング": "Closing",
  "案件管理": "Deal management",
  "決定先延ばし": "Decision delay",
  "決裁者未特定": "Decision-maker unidentified",
  "ステークホルダー": "Stakeholders",
  "提案": "Proposal",
  "初回訪問": "First visit",
  "ヒアリング": "Discovery",
  "関係構築": "Relationship building",
  "決裁者同席": "Decision-maker attendance",
  "価格": "Pricing",
  "交渉": "Negotiation",
  "情報確認": "Information check",
  "予算": "Budget",
  "移行": "Migration",
  "競合": "Competition",
  "差別化": "Differentiation",
};

// --- Product categories (deals/quotes/orders) ------------------------------
export const PRODUCT_CATEGORY_EN: Record<string, string> = {
  "OA機器": "Office equipment",
  "PC周辺機器": "PC peripherals",
  "サーバー": "Servers",
  "ソフトウェア": "Software",
  "ネットワーク機器": "Networking",
};

export function productCategoryText(lang: Lang, ja: string): Localized {
  return pickText(lang, ja, PRODUCT_CATEGORY_EN[ja]);
}

// --- Customer (company) names ----------------------------------------------
export const CUSTOMER_EN: Record<string, string> = {
  // Coaching workspace / needs_coaching + confidence
  "有限会社村田印刷": "Murata Printing Co.",
  "山田電機": "Yamada Electronics",
  "株式会社小林製作所": "Kobayashi Manufacturing Co.",
  "大和産業": "Yamato Industries",
  "東和システム": "Towa Systems",
  "北川物産": "Kitagawa Trading",
  "富士産業": "Fuji Industries",
  "松田サービス": "Matsuda Services",
  // Dashboard deals
  "株式会社アクメ商事": "Acme Trading Co.",
  "山田製作所": "Yamada Manufacturing",
  "みどり物産": "Midori Trading",
  "大和テック": "Yamato Tech",
  "北野エンジニアリング": "Kitano Engineering",
  "セントラル工業": "Central Industries",
  "光通信サービス": "Hikari Telecom",
  "丸三フーズ": "Marusan Foods",
  // Coach deal selector (from API/seed)
  "有限会社松田サービス": "Matsuda Services Co.",
  "石川産業": "Ishikawa Industries",
  "大和商事": "Yamato Trading",
  "あおぞらサービス": "Aozora Services",
  "有限会社ひかり物産": "Hikari Trading Co.",
  "有限会社富士産業": "Fuji Industries Co.",
  "有限会社山田電機": "Yamada Electronics Co.",
  "中央印刷": "Chuo Printing",
  "有限会社石川産業": "Ishikawa Industries Co.",
  "株式会社あけぼのシステム": "Akebono Systems Co.",
  "村田サービス": "Murata Services",
  "宝工業": "Takara Industries",
  "石川物産": "Ishikawa Trading",
  "有限会社光印刷": "Hikari Printing Co.",
  "有限会社誠和クリニック": "Seiwa Clinic Co.",
  "株式会社松田建設": "Matsuda Construction Co.",
  "富士物産": "Fuji Trading",
  "三幸商事": "Sanko Trading",
  "サンライズ産業": "Sunrise Industries",
  "株式会社北斗物産": "Hokuto Trading Co.",
};

export function customerText(lang: Lang, ja: string): Localized {
  return pickText(lang, ja, CUSTOMER_EN[ja]);
}

// --- Rep (salesperson) names -----------------------------------------------
export const REP_EN: Record<string, string> = {
  // Full names (coaching workspace)
  "佐藤美咲": "Misaki Sato",
  "伊藤翔": "Sho Ito",
  "渡辺さくら": "Sakura Watanabe",
  "山本健一": "Kenichi Yamamoto",
  "中村優子": "Yuko Nakamura",
  "鈴木大輔": "Daisuke Suzuki",
  "田中健太": "Kenta Tanaka",
  "高橋由美": "Yumi Takahashi",
  // Short names (dashboard)
  "佐藤": "Sato",
  "鈴木": "Suzuki",
  "高橋": "Takahashi",
  "田中": "Tanaka",
  "渡辺": "Watanabe",
  "伊藤": "Ito",
};

export function repText(lang: Lang, ja: string): Localized {
  // Person names are proper nouns: they stay Japanese in every language.
  // (Not a fallback — the kanji IS the canonical rendering, so no JP badge.)
  return { text: ja, fallback: false };
}

// --- Department names ------------------------------------------------------
export const DEPARTMENT_EN: Record<string, string> = {
  "第一営業部": "Sales Division 1",
  "第二営業部": "Sales Division 2",
  "第三営業部": "Sales Division 3",
  "営業統括部": "Sales Management Division",
};

export function departmentText(lang: Lang, ja: string): Localized {
  return pickText(lang, ja, DEPARTMENT_EN[ja]);
}

// --- Specialty tags (growth/rep profile) ------------------------------------
export const SPECIALTY_EN: Record<string, string> = {
  "複合機": "Multifunction printers",
  "サーバー": "Servers",
  "ネットワーク": "Networking",
  "PC": "PCs",
};

export function specialtyText(lang: Lang, ja: string): Localized {
  return pickText(lang, ja, SPECIALTY_EN[ja]);
}

// --- Flag messages (reliability flags) -------------------------------------
export const FLAG_MESSAGE_EN: Record<string, string> = {
  "担当の見込みは『高』だが健全度は赤": "Rep's forecast is 'high' but health is red",
  "完了予定日(2026-05-27)を過ぎても案件がオープン": "Deal still open past the expected close date (2026-05-27)",
  "41日連絡がないままアクティブ扱い": "Marked active despite 41 days without contact",
  "必須項目が未入力: 次アクション": "Required field missing: next action",
  "proposal段階への移行を裏づけるメモがない": "No note supports the move to proposal stage",
};

export function flagMessageText(lang: Lang, ja: string): Localized {
  return pickText(lang, ja, FLAG_MESSAGE_EN[ja]);
}

// --- Deal signal reasons (deal drawer) -------------------------------------
export const SIGNAL_REASON_EN: Record<string, string> = {
  "決裁者が未確認": "Decision-maker unconfirmed",
  "見積が未発行": "No quote issued",
  "直近の活動なし": "No recent activity",
  "完了予定日を超過": "Past expected close date",
  "予算が未確認": "Budget not confirmed",
  "次アクションが未設定": "No next action set",
  "スリップ回数が多い": "Too many slips",
};

export function signalReasonText(lang: Lang, ja: string): Localized {
  return pickText(lang, ja, SIGNAL_REASON_EN[ja]);
}

// --- Deal stages -----------------------------------------------------------
export const STAGE_EN: Record<string, string> = {
  proposal: "Proposal",
  negotiation: "Negotiation",
  closing: "Closing",
  qualified: "Qualified",
  discovery: "Discovery",
  prospecting: "Prospecting",
};

// --- Source corpus notes ---------------------------------------------------
export const SOURCE_NOTE_EN: Record<string, string> = {
  I01: "Respondent A. Gave A/B choices with reasoning across seven either-or scenarios.",
  I02: "Respondent B. Answered the same seven scenarios, making situation-dependent judgments explicit.",
  Q01: "Shared questionnaire. Ten open-ended questions plus seven either-or scenarios.",
};

// --- Derived coaching items (G0001–G0004) ----------------------------------
export interface ItemContentEN {
  scenario: string;
  signals: string[];
  questions: string[];
  risks: string[];
  alternatives: string[];
}

export const ITEM_EN: Record<string, ItemContentEN> = {
  G0001: {
    scenario:
      "On a first visit, a new rep opened with “How many PCs do you have? Which OS? What's your network?” and launched straight into a systems survey. The contact was reluctant to talk, and time passed with almost no concrete information drawn out.",
    signals: [
      "The contact's responses are shallow and they're reluctant to talk",
      "Questions about systems or specs get no concrete answers",
      "A relationship with the customer hasn't been established yet",
    ],
    questions: [
      "What is the single biggest challenge in your operations right now?",
      "In what situations do you typically use your PCs and network?",
      "(Before asking about your systems directly) may I first ask what matters most to you?",
    ],
    risks: [
      "Rushing to gather information on the first visit makes the customer wary and harder to build a relationship with later",
      "You move to a proposal on inaccurate information about their systems",
    ],
    alternatives: [
      "On a repeat visit where trust already exists and time is short, it can be fine to confirm the systems first",
      "For a technical deal with urgent requirements, capturing just the key points first is also an option",
    ],
  },
  G0002: {
    scenario:
      "After several meetings with a contact, a new rep abruptly asked “Could the department head join us next time?” — and the contact's expression clouded over.",
    signals: [
      "Trust with the contact is still shallow",
      "It gives the impression of going over the contact's head to the decision-maker",
      "The reason for the request to join hasn't been communicated to the contact",
    ],
    questions: [
      "Who will ultimately make the decision on this deal?",
      "Could we make the next meeting one where we can convey the benefits to the department head as well?",
      "(If the relationship is good) to save everyone's time, could we ask the head to join us once?",
    ],
    risks: [
      "A sudden request for the decision-maker to attend makes the contact feel sidelined and backfires",
      "Being overly cautious, on the other hand, delays approval and stalls the deal",
    ],
    alternatives: [
      "If you're on good terms and can make the ask, requesting attendance early to cut the effort to a decision is effective",
      "If the relationship is shallow, move in stages and float the idea only after giving the contact due respect",
    ],
  },
  G0003: {
    scenario:
      "An existing customer mentioned interest in a different product, and the new rep immediately began preparing that proposal. But the multifunction-printer deal already in progress was still stuck at “we'll review it internally,” with both its timing and certainty unclear.",
    signals: [
      "The decision timing of the in-progress deal is unconfirmed",
      "The deal's certainty has been left vague",
      "Distracted by the new proposal, the current deal isn't moving forward",
    ],
    questions: [
      "For the current printer deal, when do you expect a decision?",
      "How far along is your internal review right now?",
      "(Before moving to the new proposal) may we first move the current deal one step forward?",
    ],
    risks: [
      "Spreading across multiple deals leaves all of them half-finished and undecided",
      "The existing deal is left hanging and quietly fades away or is lost",
    ],
    alternatives: [
      "If the existing deal is highly certain and the customer's request is strong, it's fine to advance the new proposal in parallel",
      "If the other product would help close the current deal, deliberately proposing them together is also an option",
    ],
  },
  G0004: {
    scenario:
      "The department head was positive and said it was “as good as decided,” so the new rep wrote in the daily report that the deal was nearly closed. But the IT staff on the ground had yet to raise a single concrete question or concern.",
    signals: [
      "Buy-in from the on-site IT staff hasn't been confirmed",
      "The deal is judged nearly closed on the department head's impression alone",
      "Technical concerns may remain unresolved",
    ],
    questions: [
      "Are the IT staff satisfied with the proposed configuration?",
      "Are there any points or worries the team on the ground has?",
      "Have we conveyed the benefits to both the department head and the IT staff?",
    ],
    risks: [
      "The IT staff aren't convinced, and in the end the department head can't commit to the contract",
      "Slighting the technical department creates problems for future business",
    ],
    alternatives: [
      "If the IT staff are already strongly in favor, you can focus on the decision-maker's final approval",
      "For a small deal with few technical issues, proceeding decision-maker-first is a reasonable call",
    ],
  },
};

// --- Relevance hints -------------------------------------------------------
// Keyword cues for surfacing which principles bear on a pasted note. This is a
// *presentation* affordance (highlighting existing knowledge), not new business
// logic — it changes nothing the engine computes.
export const PRINCIPLE_KEYWORDS: Record<string, string[]> = {
  P001: ["検討", "社内", "別の", "新しい", "確度", "決定", "白黒", "提案", "review", "internally"],
  P002: ["値引き", "価格", "値下げ", "高い", "コスト", "discount", "price"],
  P003: ["かもしれない", "担当者", "キーマン", "曖昧", "確認"],
  P004: ["妥協", "次善", "交渉", "プラン"],
  P005: ["予算", "資金", "お金", "費用", "budget"],
  P006: ["部長", "IT", "技術", "現場", "決裁", "担当者"],
  P007: ["移行", "負荷", "技術部門", "作業"],
  P008: ["初回", "訪問", "環境", "ネットワーク", "PC", "関係", "ヒアリング", "first visit"],
  P009: ["競合", "他社", "比較", "下げる"],
  P010: ["選定", "基準", "決める", "比較", "競合", "お客様"],
  P011: ["同席", "決裁者", "部長", "次回", "クロージング"],
};

// --- Pickers ---------------------------------------------------------------
export interface Localized {
  text: string;
  /** true when EN was requested but only the JA original exists. */
  fallback: boolean;
}

export function pickText(lang: Lang, ja: string, en?: string): Localized {
  if (lang === "en") {
    if (en && en.trim()) return { text: en, fallback: false };
    return { text: ja, fallback: true };
  }
  return { text: ja, fallback: false };
}

export function pickList(
  lang: Lang,
  ja: string[],
  en?: string[],
): { vals: string[]; fallback: boolean } {
  if (lang === "en") {
    if (en && en.length === ja.length) return { vals: en, fallback: false };
    return { vals: ja, fallback: true };
  }
  return { vals: ja, fallback: false };
}

export function principleText(lang: Lang, p: { principle_id: string; statement: string }): Localized {
  return pickText(lang, p.statement, PRINCIPLE_EN[p.principle_id]);
}

export function tagText(lang: Lang, tag: string): Localized {
  return pickText(lang, tag, TAG_EN[tag]);
}

export function sourceNoteText(lang: Lang, id: string, ja: string): Localized {
  return pickText(lang, ja, SOURCE_NOTE_EN[id]);
}

// ---------------------------------------------------------------------------
// Coach output lines (deterministic engine text from senpai/coach/review.py).
//
// These are the JA strings the Review Coach emits for the six lenses. They're a
// fixed, enumerable set, so we translate them by exact match here — a pure
// presentation step that never touches the engine. Lines we don't recognise
// (deal-fused signals, flag messages) fall back to JA + a "JP Original" badge,
// honoring the same fallback contract used everywhere else.
// ---------------------------------------------------------------------------
export const COACH_LINE_EN: Record<string, string> = {
  // --- decision_maker lens ---
  "誰が最終的に決めるのか(決裁者)が見えていない":
    "It isn't clear who ultimately decides (the decision-maker).",
  "決裁者・意思決定に関わる人": "The decision-maker and others involved in the decision",
  "この件はどなたが最終的にご決定されますか？他に関わる方はいますか？":
    "Who will make the final decision on this? Is anyone else involved?",
  "決裁ルートが不明なまま進むと、終盤で想定外の関与者が出て止まりやすい":
    "Moving ahead without a clear approval path invites an unexpected stakeholder late on, which stalls the deal.",
  "決裁者が誰で、何を重視するか(コスト/安心/現場負担)":
    "Who the decision-maker is and what they weigh (cost / peace of mind / burden on staff).",
  // --- timeline lens ---
  "次の打ち合わせや意思決定の時期が決まっていない":
    "No date is set for the next meeting or the decision.",
  "次回接触日・意思決定の時期": "The next contact date and the decision timing",
  "社内でのご検討はいつ頃まとまりそうですか？次にお話しする日を今決めておけますか？":
    "When do you expect your internal review to wrap up? Could we lock in our next conversation now?",
  "期日がないと『検討します』のまま自然消滅しやすい":
    "With no deadline, a “we'll think about it” tends to quietly fade away.",
  "顧客の導入希望時期と予算サイクル(年度末など)":
    "The customer's target rollout timing and budget cycle (e.g. fiscal year-end).",
  // --- criteria lens ---
  "何を基準に判断されるのかが分かっていない": "It's unclear what criteria the decision will rest on.",
  "意思決定の判断基準": "The decision criteria",
  "ご判断にあたって特に重視される点はどこですか？(価格/サポート/実績 など)":
    "What matters most in your decision? (price / support / track record, etc.)",
  "判断基準が不明だと、的を外した提案を続けてしまう":
    "Without knowing the criteria, you keep making proposals that miss the mark.",
  "顧客が重視する価値(価格 vs 安心 vs 実績)":
    "The value the customer prioritizes (price vs. peace of mind vs. track record).",
  // --- next_step lens ---
  "次の具体的な一歩(誰が・何を)が決まっていない":
    "The next concrete step (who does what) isn't decided.",
  "次の具体的アクションと担当": "The next concrete action and who owns it",
  "次は私たちから何をお持ちすればよいですか？こちらの宿題を一つ決めませんか？":
    "What should we bring you next time? Shall we agree on one action item for our side?",
  "ボールの所在が曖昧だと案件が宙に浮く":
    "When it's unclear whose court the ball is in, the deal drifts.",
  "こちらが主導権を保てる次の一手があるか":
    "Whether there's a next move that keeps the initiative on your side.",
  // --- budget lens ---
  "予算の有無・規模が確認できていない": "Whether a budget exists, and its size, hasn't been confirmed.",
  "予算の所在と規模": "Whether budget is in place and how large",
  "今回のご予算感や、予算の確保状況は伺えますか？":
    "Could you share your budget expectations and whether funding is secured?",
  "予算未確認のまま提案すると、後で金額が理由で破談になりやすい":
    "Proposing before confirming budget often leads to the deal collapsing over price later.",
  "予算が確保済みか、これから稟議か": "Whether budget is already secured or still pending approval.",
  // --- presence detectors (stall / competition) ---
  "顧客の言葉に停滞サインがある。受け身で待つと流れやすい":
    "The customer's wording shows a stalling sign; waiting passively lets it slip away.",
  "他社さんと比較されていますか？どこと、どの点で比べられていますか？":
    "Are you comparing us with other vendors? Which ones, and on what points?",
  "競合がいる → 価格以外の差別化軸(保守・実績)が要る":
    "A competitor is in play → you need a differentiator beyond price (maintenance, track record).",
  // --- next_actions ---
  "その場で次回の打ち合わせ日を仮押さえし、案件を宙に浮かせない":
    "Pencil in the next meeting date on the spot so the deal doesn't drift.",
  "現場担当に『最終決定はどなたと進めますか』と決裁プロセスを確認する":
    "Ask your contact “Who do we work with on the final decision?” to map the approval process.",
  "判断基準をヒアリングしてから、刺さる比較軸で再提案する":
    "Discover the decision criteria first, then re-propose on the comparison points that land.",
  "予算の確保状況を確認し、決裁者向けの費用対効果1枚を用意する":
    "Confirm whether budget is secured and prepare a one-page cost-benefit for the decision-maker.",
  "価格勝負を避け、保守体制・導入後サポートで違いを示す":
    "Avoid competing on price; differentiate on maintenance and post-rollout support.",
  "現状で大きな抜けは見当たらない。次の一歩を予定どおり進める":
    "No major gaps stand out for now; proceed with the next step as planned.",
  // --- fused deal-data signals (scoring.py / flags.py), static ones ---
  "決裁者が未特定": "The decision-maker hasn't been identified.",
  "直近30日の活動が0件": "No activity logged in the last 30 days.",
};

// Field names inside the "missing required fields" flag.
const FIELD_EN: Record<string, string> = {
  "決裁者": "decision-maker", "金額": "amount",
  "完了予定日": "expected order date", "日報": "daily report",
};

// Templated coach lines: a fixed frame with a variable slice (a phrase the
// customer used, or a deal stage/band). We translate the frame and keep the
// quoted source phrase verbatim — that quote is intentional source material.
const COACH_LINE_TEMPLATES: { re: RegExp; en: (m: RegExpMatchArray) => string }[] = [
  { re: /^停滞を示す言葉「(.+?)」が出ている$/, en: (m) => `A stalling phrase (“${m[1]}”) appears in the customer's words.` },
  { re: /^競合の存在を示す言葉「(.+?)」がある$/, en: (m) => `A phrase signaling a competitor (“${m[1]}”) is present.` },
  { re: /^現在の段階: (.+?)\(健全度 (.+?)\)$/, en: (m) => `Current stage: ${m[1]} (health: ${m[2]}).` },
  // --- fused deal-data signals (scoring.py reasons) ---
  { re: /^(\d+)日間接触なし\(目安(\d+)日の2倍超\)$/, en: (m) => `${m[1]} days without contact (over 2× the ${m[2]}-day benchmark).` },
  { re: /^(\d+)日間接触なし\(目安(\d+)日超\)$/, en: (m) => `${m[1]} days without contact (over the ${m[2]}-day benchmark).` },
  { re: /^(.+?)に(\d+)日滞留\(目安(\d+)日\)$/, en: (m) => `Stuck at ${m[1]} for ${m[2]} days (benchmark ${m[3]} days).` },
  { re: /^完了予定日\((.+?)\)を過ぎても未受注$/, en: (m) => `Past the expected order date (${m[1]}) with no order yet.` },
  { re: /^ランクが (.+?) → (.+?) に低下$/, en: (m) => `Rank dropped from ${m[1]} → ${m[2]}.` },
  { re: /^直近の日報に停滞サイン「(.+?)」$/, en: (m) => `A stall signal (“${m[1]}”) appears in the latest daily report.` },
  // --- reliability flags (flags.py messages) ---
  { re: /^完了予定日\((.+?)\)を過ぎても案件がオープン$/, en: (m) => `Past the expected order date (${m[1]}); the deal is still open.` },
  { re: /^(\d+)日活動がないままアクティブ扱い$/, en: (m) => `Marked active despite ${m[1]} days with no activity.` },
  { re: /^必須項目が未入力: (.+)$/, en: (m) => `Missing required fields: ${m[1].split("・").map((f) => FIELD_EN[f] ?? f).join(", ")}.` },
  { re: /^ランクは『(.+?)』だが健全度は赤$/, en: (m) => `Rank is “${m[1]}” but health is red.` },
  { re: /^(.+?)への更新を裏づける日報がない$/, en: (m) => `No daily report supports the update to ${m[1]}.` },
];

/**
 * Translate one deterministic coach line for display. JA mode returns it
 * unchanged; EN mode returns the exact/templated translation, or the JA
 * original with `fallback: true` (the caller shows a "JP Original" badge).
 */
const SIGNAL_PREFIX = "案件データ上のサイン: ";

export function coachLineText(lang: Lang, ja: string): Localized {
  if (lang !== "en") return { text: ja, fallback: false };
  // "Deal-data signal: <reason>" — translate the inner reason recursively so the
  // fused scoring signal reads fully in English.
  if (ja.startsWith(SIGNAL_PREFIX)) {
    const inner = coachLineText(lang, ja.slice(SIGNAL_PREFIX.length));
    return { text: `Deal-data signal: ${inner.text}`, fallback: inner.fallback };
  }
  const exact = COACH_LINE_EN[ja];
  if (exact) return { text: exact, fallback: false };
  for (const tpl of COACH_LINE_TEMPLATES) {
    const m = ja.match(tpl.re);
    if (m) return { text: tpl.en(m), fallback: false };
  }
  return { text: ja, fallback: true };
}

// ---------------------------------------------------------------------------
// Seed coach examples (the "start from an example" cards). The engine reads
// Japanese cue phrases, so the JA note always drives coaching — `engineNote`
// stays Japanese. Only the *displayed* title/note/hint switch to English, with
// human-written translations (no machine translation on render). Keyed by the
// JA title the API/fixtures emit.
// ---------------------------------------------------------------------------
export interface CoachExampleEN {
  title: string;
  note: string;
  hint: string;
}

export const COACH_EXAMPLE_EN: Record<string, CoachExampleEN> = {
  "前向きだが先送り": {
    title: "Decision delayed",
    note: "The customer will review it internally and get back to us. The reaction was positive.",
    hint: "A classic case where the decision-maker, deadline, and next step are easily missed.",
  },
  "競合比較中": {
    title: "Competitive evaluation",
    note: "The customer is comparing us with a competitor's product and said our price is high. I plan to resubmit a quote before the next meeting.",
    hint: "Find your differentiation before getting pulled into a price war.",
  },
  "初回訪問の報告": {
    title: "Initial visit report",
    note: "First visit. I was able to go over the customer's PC environment and network setup. The contact seemed busy.",
    hint: "Rushing to gather information while relationship-building and grasping their concerns fall behind.",
  },
  "部長が前向き": {
    title: "Department head interested",
    note: "The department head is positive and it feels nearly decided. I haven't been able to meet the IT staff on the ground.",
    hint: "Are you calling the deal nearly closed on the decision-maker's impression alone?",
  },
};

export interface LocalizedExample {
  title: string;
  note: string;       // what to display in the chat bubble
  hint: string;
  engineNote: string; // what to send to the keyword-based coach (always JA)
  fallback: boolean;  // EN requested but only JA exists
}

export function coachExampleText(
  lang: Lang,
  ex: { title: string; note: string; hint: string },
): LocalizedExample {
  if (lang === "en") {
    const en = COACH_EXAMPLE_EN[ex.title];
    if (en) return { ...en, engineNote: ex.note, fallback: false };
    return { title: ex.title, note: ex.note, hint: ex.hint, engineNote: ex.note, fallback: true };
  }
  return { title: ex.title, note: ex.note, hint: ex.hint, engineNote: ex.note, fallback: false };
}

/**
 * Build a JA→EN lookup for senior "drawer" tips. The playbook surfaces the
 * first question/signal/scenario of an approved knowledge item; ITEM_EN already
 * holds the English for each, so we zip them by item to translate the tip in
 * place — exactly the "use existing content-i18n mappings" path.
 */
export function buildTipMap(
  items: { item_id: string; questions: string[]; signals: string[]; scenario: string }[],
): Record<string, string> {
  const map: Record<string, string> = {};
  for (const it of items) {
    const en = ITEM_EN[it.item_id];
    if (!en) continue;
    it.questions.forEach((j, i) => { if (en.questions[i]) map[j] = en.questions[i]; });
    it.signals.forEach((j, i) => { if (en.signals[i]) map[j] = en.signals[i]; });
    if (it.scenario && en.scenario) map[it.scenario] = en.scenario;
  }
  return map;
}
