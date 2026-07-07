# Senpai Capability & Tool-Stress Test Prompt Ledger

These Japanese prompts are designed to trigger massive parallel tool-calling chains (between 5 and 10 tools simultaneously or sequentially) within the Unified Command Center. Copy-paste these prompts to show managers the sheer cognitive depth and deterministic grounding of Project Senpai.

---

## 🚀 MEGA PROMPT 1: The "Ultimate Customer Visit Prep" (10 Tools)

### Exact Prompt to Copy-Paste:
```text
明日、有限会社村田印刷（C13 / D001）を訪問する予定です。事前準備として、最新のSPR記録を確認し、過去活動日報からサーバーに関する要約を意味検索してください。また、顧客のIT環境、当社のサーバー製品情報（SRV20など）の価格とスペック、この案件の健康状態（ヘルススコア）、および過去の類似案件や先輩のプレイブック（値引き交渉）の知見を全て集めてください。さらに、明日のカレンダー予定を確認し、訪問後に送るフォローアップ用メールの下書きと、来週の打合せ調整用の会議スケジュール（仮登録）を一度に行い、最後にこれらを元にした正式な提案資料を作成してください。
```

### Expected Tools Called (10 Tools):
1. `query_spr`
2. `search_notes`
3. `lookup_customer_environment`
4. `search_products` / `get_product_info`
5. `score_deal_health`
6. `find_similar_deals`
7. `retrieve_playbook`
8. `get_calendar`
9. `send_email`
10. `schedule_meeting` / `generate_proposal`

### Pros for the Demo:
* **Massive Tool Fan-out**: Demonstrates the AdaptiveScheduler grouping and executing multiple read-only requests (CRM, semantic notes, product catalog, calendar, playbook) in parallel, minimizing latency.
* **Context-Bound Document Creation**: Prepares a flawless pitch email and meeting invite while generating a ready-to-download, branded PPTX proposal containing zero LLM-invented numbers.
* **Complete Pre-Call Intelligence**: Combines internal historical insights, IT topology, and expert tactics into a single brief, proving that reps no longer need to spend hours digging through legacy database tables.

---

## 📊 MEGA PROMPT 2: The "Manager Portfolio Triage & Active Intervention" (9 Tools)

### Exact Prompt to Copy-Paste:
```text
大塚商会の営業管理職として、チームのパイプライン状況を俯瞰したいです。チーム全体のパイプライン概況、日報ダイジェスト、今週アプローチすべき要注意案件一覧、および最も指導が必要なコーチング対象のロールアップを取得してください。さらに、現在進行中のD001、D012、D168の案件健全度（ヘルススコア）を並行して比較し、共通するリスクを特定してください。状況を確認した後、伊藤翔さん宛に「D001案件の健康状態に関する進捗確認」について面談を調整するカレンダーの空き時間を確認し、面談調整メッセージの下書きを自動作成してください。
```

### Expected Tools Called (9 Tools):
1. `team_pipeline_overview`
2. `team_report_digest`
3. `rep_coaching_focus`
4. `list_at_risk_deals`
5. `score_deal_health` (parallelized via `_multi_entity_gather_calls`)
6. `query_spr` (parallelized for D001, D012, D168)
7. `get_calendar`
8. `schedule_meeting`
9. `draft_message`

### Pros for the Demo:
* **The "Compare" Multi-Entity Trigger**: Showcases the backend's speculative `_multi_entity_gather_calls` interceptor, triggering 6 concurrent queries instantly without spiraling.
* **End-to-End Triage & Action Loop**: Enables the manager to evaluate high-level pipeline health, dive deep into specific high-risk opportunities, check schedules, and compose corrective rep messages in a single chat turn.
* **Zero-Math Reliance**: Proves that pipeline statistics, risk bands, and coaching focus scores are computed with 100% mathematical integrity natively on the CPU.

---

## ⚔️ MEGA PROMPT 3: The "Competitor Fightback & Quote Assembly" (8 Tools)

### Exact Prompt to Copy-Paste:
```text
株式会社ヤマト食品（C09 / D021）から「他社製品と比較中（相見積もり）」と言われ、10%の値引きを求められています。交渉に向けた対抗策として、顧客のIT環境を確認し、過去の活動報告から「競合」や「比較」に関する日報を意味検索してください。また、先輩のプレイブックから「差別化」や「値引き交渉」の原則を引き出してください。これらを踏まえて、当社の27インチモニター（MON27）4台分の見積（10%値引き適用、消費税10%）を作成してください。さらに、現在の季節的・予算的な時期に応じた予算交渉のアドバイスを出し、顧客へ提示するメールの下書きと、カレンダーに登録するWeb商談のスケジュール調整をセットで実行してください。
```

### Expected Tools Called (8 Tools):
1. `lookup_customer_environment`
2. `search_notes` (query="競合 比較中")
3. `retrieve_playbook` (tags=["差別化", "値引き"])
4. `search_products` / `get_product_info`
5. `create_quote` (MON27, qty: 4, discount_pct: 10)
6. `get_seasonal_context`
7. `send_email`
8. `schedule_meeting`

### Pros for the Demo:
* **Negotiation Under Fire**: Unlocks playbooks and historical deal patterns (the Experience pillar) to guide junior reps away from lazy, margin-destroying discounts.
* **Automated Calculations**: Verifies standard catalog prices, applies discount formulas, adds sales tax, and generates a formatted quote draft with 100% precision.
* **Seasonal Alignment**: Injects local Japanese fiscal context (e.g., Q4 year-end budget exhaustion), training reps to time negotiations with client spending cycles.

---

## 📂 MEGA PROMPT 4: The "Unified Sandboxed Document Prep" (8 Tools)

### Exact Prompt to Copy-Paste:
```text
私のローカルファイルから「Yamato」や「estimate」に関連するお見積書やメモ（PDF、DOCX、XLSX、TXT等）を探し出し、そこに記載されている価格や構成を要約してください。さらに、大塚商会の製品カタログから適合するサーバー機器情報を取得し、現在の四半期の予算枠情報を確認した上で、この内容に基づいて大塚商会の正式な製品見積書を新規作成し、担当者へ送るためのメール下書きを用意してください。最後に、これら会話やローカルファイルの文脈（これまでの会話・確定済みの文脈）をすべて引き継ぎ、有限会社村田印刷（C13）のD001案件の正式な提案資料（PPTX）を直接作成してダウンロードできるようにしてください。
```

### Expected Tools Called (8 Tools):
1. `search_workspace_documents`
2. `get_product_info`
3. `get_seasonal_context`
4. `create_quote`
5. `send_email`
6. `query_spr`
7. `generate_pptx` / `generate_proposal`
8. `get_calendar`

### Pros for the Demo:
* **Runtime DAG Expansion (`ctx.expand`)**: Scans the filesystem, detects relevant documents, and spawns parallel extraction threads, demonstrating deep sandboxed document parsing.
* **The "Wrong-Company" Protection**: Uses `SessionFocus` to ensure the generated proposal targets the correct entity (`C13`), preventing text context bleed.
* **Rich Artifact Generation**: Leverages `render_pptx` with server-side `matplotlib` to embed authentic ROI charts and Otsuka corporate slides instantly.

---

## 🧹 MEGA PROMPT 5: The "Local Sandbox Organizer & Preservation" (7 Tools)

### Exact Prompt to Copy-Paste:
```text
私のワークスペースにあるファイルを一度整理してください。その前に、ローカルファイルにあるすべての打合せ議事録（notesやmemo）を検索し、それらの要約を作成してください。さらに、現在の四半期の予算サイクル情報を確認し、整理プレビューの内容を特定のMarkdownファイル「workspace_summary.md」にメモ保存してください。整理完了後に、次回の顧客訪問に向けたメールの下書きを作成してください。
```

### Expected Tools Called (7 Tools):
1. `search_workspace_documents` (query="notes OR memo")
2. `move_workspace_document` (confirm=False for organize preview)
3. `get_seasonal_context`
4. `edit_workspace_document` (confirm=False for summary note preview)
5. `send_email`
6. `get_calendar`
7. `query_spr`

### Pros for the Demo:
* **The Two-Turn Confirmation Gate**: Forces a read-only organize preview before mutating files, showing the safety controls in place to protect enterprise data.
* **Workspace Persistence**: Authors meeting summaries from local context and saves them back to disk via confirmation-gated markdown generation.
* **Bilingual Translation Security**: Proves that files are read, parsed, and translated natively, maintaining consistent terminology across turns.
