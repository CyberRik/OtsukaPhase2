"""Deterministic generator for Senpai's seed data, in the REAL SPR schema.

Run `python -m senpai.data.gen_seed` to (re)write senpai/data/seed/*.json. Output
is byte-stable (fixed seed + fixed REFERENCE_DATE), and the JSON is committed so
the dashboard and tests run with zero setup.

The four production tables mirror `Schema.md` field-for-field so that swapping in
real data later is a drop-in:
    deals.json · orders.json · quotes.json · sales_activities.json
Plus supplementary reference data that the SPR tables only *reference* (these would
come from master data / other systems / knowledge mining, not the SPR export):
    reps.json · customers.json · products.json · environments.json · playbook.json
    customer_aliases.json (English/romaji forms, auto-derived from the name parts)
    rank_history.json (a normalized order-rank change log, one row per change, keyed
        by deal_id — NOT part of the SPR `deals` table, which stays field-for-field)

Content is Japanese (data) to match the Otsuka context; field names stay English.

Scale & shape
-------------
This is a *large, multi-year* synthetic pipeline (~150 customers, ~520 deals across
FY2024 Q1 → FY2026 Q1). Deals fall into three dated cohorts so the live views stay
bounded while history accumulates:
  · live pipeline   — order_rank in OPEN_RANKS, dated near REFERENCE_DATE (drives the
                      dashboard / scoring / Matsuda demo).
  · historical won  — 1_Confirmed, spread across prior fiscal years, with real
                      ordered_at/shipped_at so order & revenue history has depth.
  · historical dead — 7_Lost / 8_Cancelled, spread across prior years.
`store.open_deals()` filters to OPEN_RANKS, so the live pipeline the manager sees
stays ~140 even though the corpus is 500+.

Anchors (kept stable so tests + the Matsuda demo keep passing):
  · Reps R01–R08 unchanged (esp. R05 = 伊藤翔). New reps are appended as R09+.
  · D001–D004 are deliberately dead (strong rank but stale, order date passed, no
    decision-maker) so the manager view flags real risk on first load.
  · D001's customer is 有限会社村田印刷.
  · Customer C28 is a 松田 account with a rich open pipeline (the Matsuda demo default).
A full order-rank history (the Schema.md open question) is modelled in a *separate*
`rank_history.json`, so the SPR `deals` table stays field-for-field with the schema.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta

from senpai import config

REF = config.REFERENCE_DATE


def _iso(days_ago: int) -> str:
    """A date `days_ago` days before the fixed reference date (negative = future)."""
    return (REF - timedelta(days=days_ago)).isoformat()


def _fy(d_iso: str) -> tuple[int, int]:
    """Japanese fiscal year/quarter for a YYYY-MM-DD date (FY starts in April)."""
    y, m, _ = (int(x) for x in d_iso.split("-"))
    fy = y if m >= 4 else y - 1
    q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3,
         1: 4, 2: 4, 3: 4}[m]
    return fy, q


# ---------------------------------------------------------------------------
# Supplementary reference data (referenced by sales_info / product_code, etc.)
# ---------------------------------------------------------------------------

# Reps are referenced from the SPR tables via sales_info.employee_id.
# R01–R08 are load-bearing anchors (R05 = 伊藤翔 is asserted by tests) and must not
# change; R09+ are appended to enrich the manager/coaching rollups and org structure.
REPS = [
    {"employee_id": "R01", "name": "田中健太", "role": "senior",
     "department": "第一営業部", "division": "法人2課",
     "specialty_tags": ["複合機", "提案", "クロージング"], "is_top_performer": True},
    {"employee_id": "R02", "name": "佐藤美咲", "role": "expert",
     "department": "第一営業部", "division": "法人2課",
     "specialty_tags": ["ネットワーク", "セキュリティ"], "is_top_performer": True},
    {"employee_id": "R03", "name": "鈴木大輔", "role": "expert",
     "department": "第二営業部", "division": "法人1課",
     "specialty_tags": ["サーバー", "クラウド"], "is_top_performer": False},
    {"employee_id": "R04", "name": "高橋由美", "role": "senior",
     "department": "第二営業部", "division": "法人1課",
     "specialty_tags": ["ソフトウェア", "保守"], "is_top_performer": True},
    {"employee_id": "R05", "name": "伊藤翔", "role": "junior",
     "department": "第一営業部", "division": "法人2課",
     "specialty_tags": ["複合機"], "is_top_performer": False},
    {"employee_id": "R06", "name": "渡辺さくら", "role": "junior",
     "department": "第二営業部", "division": "法人1課",
     "specialty_tags": ["ソフトウェア"], "is_top_performer": False},
    {"employee_id": "R07", "name": "山本健一", "role": "junior",
     "department": "第一営業部", "division": "法人2課",
     "specialty_tags": ["ネットワーク"], "is_top_performer": False},
    {"employee_id": "R08", "name": "中村優子", "role": "senior",
     "department": "第二営業部", "division": "法人1課",
     "specialty_tags": ["クラウド", "提案"], "is_top_performer": False},
    # --- appended reps (R09+) — more departments / divisions / specialties ----
    {"employee_id": "R09", "name": "小林直樹", "role": "expert",
     "department": "第三営業部", "division": "法人1課",
     "specialty_tags": ["ストレージ", "サーバー"], "is_top_performer": True},
    {"employee_id": "R10", "name": "加藤美穂", "role": "senior",
     "department": "第三営業部", "division": "法人2課",
     "specialty_tags": ["セキュリティ", "提案", "クロージング"], "is_top_performer": True},
    {"employee_id": "R11", "name": "吉田亮", "role": "junior",
     "department": "第三営業部", "division": "法人1課",
     "specialty_tags": ["複合機", "ソフトウェア"], "is_top_performer": False},
    {"employee_id": "R12", "name": "山田彩", "role": "junior",
     "department": "第三営業部", "division": "法人2課",
     "specialty_tags": ["ネットワーク"], "is_top_performer": False},
    {"employee_id": "R13", "name": "佐々木拓海", "role": "expert",
     "department": "第一営業部", "division": "法人1課",
     "specialty_tags": ["クラウド", "バックアップ"], "is_top_performer": False},
    {"employee_id": "R14", "name": "松本千尋", "role": "senior",
     "department": "第一営業部", "division": "法人1課",
     "specialty_tags": ["保守", "役務", "提案"], "is_top_performer": True},
    {"employee_id": "R15", "name": "井上海斗", "role": "junior",
     "department": "第二営業部", "division": "法人2課",
     "specialty_tags": ["サーバー"], "is_top_performer": False},
    {"employee_id": "R16", "name": "木村奈々", "role": "junior",
     "department": "第二営業部", "division": "法人2課",
     "specialty_tags": ["RPA", "ソフトウェア"], "is_top_performer": False},
    {"employee_id": "R17", "name": "林大地", "role": "expert",
     "department": "第三営業部", "division": "法人1課",
     "specialty_tags": ["ネットワーク", "セキュリティ"], "is_top_performer": True},
    {"employee_id": "R18", "name": "清水あかね", "role": "junior",
     "department": "第三営業部", "division": "法人2課",
     "specialty_tags": ["複合機"], "is_top_performer": False},
    {"employee_id": "R19", "name": "斎藤陽介", "role": "senior",
     "department": "第二営業部", "division": "法人1課",
     "specialty_tags": ["ストレージ", "保守"], "is_top_performer": False},
    {"employee_id": "R20", "name": "山口美月", "role": "junior",
     "department": "第一営業部", "division": "法人1課",
     "specialty_tags": ["ソフトウェア", "クラウド"], "is_top_performer": False},
    {"employee_id": "R21", "name": "森田圭吾", "role": "expert",
     "department": "第一営業部", "division": "法人1課",
     "specialty_tags": ["サーバー", "ストレージ"], "is_top_performer": False},
    {"employee_id": "R22", "name": "池田結衣", "role": "junior",
     "department": "第三営業部", "division": "法人2課",
     "specialty_tags": ["役務", "保守"], "is_top_performer": False},
    {"employee_id": "R23", "name": "橋本悠真", "role": "senior",
     "department": "第二営業部", "division": "法人2課",
     "specialty_tags": ["提案", "クロージング", "複合機"], "is_top_performer": True},
    {"employee_id": "R24", "name": "石川さやか", "role": "junior",
     "department": "第三営業部", "division": "法人1課",
     "specialty_tags": ["セキュリティ"], "is_top_performer": False},
]

# --- Rep skill model --------------------------------------------------------
# A single deterministic "skill profile" per rep DRIVES the realism of the daily
# reports/cards/challenges below, so the coaching engine can later *rediscover*
# each rep's recurring weakness from the data (the demo is a closed loop, not a
# gimmick). Derived only from role + a per-rep stable seed — independent of the
# main generation RNG, so enriching reports never disturbs amounts/ranks/dates.
#   weaknesses : themes the rep tends to leave out of their notes / not chase
#   improving  : a junior whose weaknesses fade over fiscal years (the longitudinal
#                signal Phase-2 progress tracking reads).
# Themes map to the Review Coach's absence lenses + discovery (customer_challenge).
_WEAKNESS_POOL = ["decision_maker", "timeline", "budget", "criteria",
                  "next_step", "discovery", "stall"]


def _build_rep_skill() -> dict[str, dict]:
    skills: dict[str, dict] = {}
    for r in REPS:
        h = random.Random(f"skill|{r['employee_id']}")
        role = r["role"]
        n_weak = {"junior": 2, "senior": 1, "expert": 0}.get(role, 1)
        if role == "expert" and h.random() < 0.3:
            n_weak = 1                                  # a few experts still have one gap
        weaknesses = set(h.sample(_WEAKNESS_POOL, n_weak)) if n_weak else set()
        improving = role == "junior" and h.random() < 0.5
        skills[r["employee_id"]] = {"weaknesses": weaknesses,
                                    "improving": improving, "role": role}
    return skills


REP_SKILL = _build_rep_skill()

# Product master. major/mid/minor mirror the orders/quotes category columns.
# Codes MFP30/MFP15/LP14/SRV20/NSW24/OFFICE/AV365 are the original seven (kept
# stable); the rest broaden the catalog across Otsuka's real lines (OA, PC, server,
# storage, network, software, and 役務/services).
PRODUCTS = [
    # --- OA機器 ---------------------------------------------------------------
    {"product_code": "MFP30", "product_name": "カラー複合機 3000",
     "manufacturer_model_number": "OTS-MFP-3000", "supplier": "大塚OEM",
     "major": "OA機器", "mid": "複合機", "minor": "A3カラー複合機",
     "standard_unit_price": 240000, "specs": "A3カラー複合機 / 30ppm / 両面",
     "manual_ja": "初期設定はネットワーク経由で自動検出。トナーは型番TN-30を使用。"},
    {"product_code": "MFP15", "product_name": "モノクロ複合機 1500",
     "manufacturer_model_number": "OTS-MFP-1500", "supplier": "大塚OEM",
     "major": "OA機器", "mid": "複合機", "minor": "A4モノクロ複合機",
     "standard_unit_price": 96000, "specs": "A4モノクロ複合機 / 25ppm",
     "manual_ja": "省スペース設置可。両面印刷はオプション。"},
    {"product_code": "MFPC25", "product_name": "カラー複合機 2500",
     "manufacturer_model_number": "OTS-MFP-2500", "supplier": "大塚OEM",
     "major": "OA機器", "mid": "複合機", "minor": "A3カラー複合機",
     "standard_unit_price": 180000, "specs": "A3カラー複合機 / 25ppm / 両面 / フィニッシャ対応",
     "manual_ja": "中規模オフィス向け。クラウド連携スキャンに対応。"},
    {"product_code": "SCN10", "product_name": "業務用スキャナー S10",
     "manufacturer_model_number": "OTS-SCN-10", "supplier": "大塚OEM",
     "major": "OA機器", "mid": "スキャナー", "minor": "ドキュメントスキャナー",
     "standard_unit_price": 78000, "specs": "両面同時読取 / 60ppm / ADF対応",
     "manual_ja": "電子帳簿保存法対応。OCRソフトを同梱。"},
    {"product_code": "PRJ40", "product_name": "プロジェクター P40",
     "manufacturer_model_number": "PRJ-40HD", "supplier": "東京電子",
     "major": "OA機器", "mid": "プレゼン機器", "minor": "プロジェクター",
     "standard_unit_price": 65000, "specs": "4000lm / フルHD / HDMI×2",
     "manual_ja": "会議室の常設設置に対応。ランプ寿命は約6000時間。"},
    {"product_code": "LBP20", "product_name": "レーザープリンタ L20",
     "manufacturer_model_number": "LBP-20N", "supplier": "東京電子",
     "major": "OA機器", "mid": "プリンタ", "minor": "A4レーザープリンタ",
     "standard_unit_price": 42000, "specs": "A4モノクロ / 35ppm / 有線+無線",
     "manual_ja": "ドライバはWeb自動配布に対応。トナーはTN-20を使用。"},
    # --- PC周辺機器 -----------------------------------------------------------
    {"product_code": "LP14", "product_name": "ノートPro 14",
     "manufacturer_model_number": "NB-PRO-14", "supplier": "東京電子",
     "major": "PC周辺機器", "mid": "モバイル端末", "minor": "ノートPC",
     "standard_unit_price": 168000, "specs": "14型 / Core i7 / 16GB / 512GB SSD",
     "manual_ja": "法人向けキッティング対応。3年保証オプションあり。"},
    {"product_code": "DT08", "product_name": "デスクトップ Biz 8",
     "manufacturer_model_number": "DT-BIZ-8", "supplier": "東京電子",
     "major": "PC周辺機器", "mid": "据置端末", "minor": "デスクトップPC",
     "standard_unit_price": 128000, "specs": "Core i5 / 16GB / 512GB SSD / 小型筐体",
     "manual_ja": "省スペース筐体。資産管理エージェントを初期導入可能。"},
    {"product_code": "MON27", "product_name": "27型モニター M27",
     "manufacturer_model_number": "MON-27W", "supplier": "東京電子",
     "major": "PC周辺機器", "mid": "ディスプレイ", "minor": "液晶モニター",
     "standard_unit_price": 34000, "specs": "27型 / WQHD / USB-C給電",
     "manual_ja": "高さ調整・ピボット対応。USB-C 1本でノートPCと接続可。"},
    {"product_code": "DOCK1", "product_name": "ドッキングステーション D1",
     "manufacturer_model_number": "DCK-1U", "supplier": "東京電子",
     "major": "PC周辺機器", "mid": "周辺機器", "minor": "ドック",
     "standard_unit_price": 22000, "specs": "USB-C / HDMI×2 / 有線LAN / PD100W",
     "manual_ja": "ノートPCの拡張に。複数台の一括キッティングに対応。"},
    {"product_code": "TAB10", "product_name": "業務用タブレット T10",
     "manufacturer_model_number": "TAB-10B", "supplier": "東京電子",
     "major": "PC周辺機器", "mid": "モバイル端末", "minor": "タブレット",
     "standard_unit_price": 58000, "specs": "10.5型 / LTE対応 / MDM対応",
     "manual_ja": "店舗・現場向け。MDMで一括管理可能。"},
    # --- サーバー / ストレージ ------------------------------------------------
    {"product_code": "SRV20", "product_name": "ラックサーバー R20",
     "manufacturer_model_number": "SRV-R20", "supplier": "日本サーバ販売",
     "major": "サーバー", "mid": "ラックサーバー", "minor": "1Uサーバー",
     "standard_unit_price": 520000, "specs": "1U / Xeon / 64GB / NVMe x2",
     "manual_ja": "RAID1構成を推奨。設置にはラックと空調の確認が必要。"},
    {"product_code": "SRV40", "product_name": "タワーサーバー T40",
     "manufacturer_model_number": "SRV-T40", "supplier": "日本サーバ販売",
     "major": "サーバー", "mid": "タワーサーバー", "minor": "タワーサーバー",
     "standard_unit_price": 380000, "specs": "Xeon / 32GB / SATA x4 / 静音",
     "manual_ja": "サーバー室不要の静音設計。小規模オフィス向け。"},
    {"product_code": "NAS08", "product_name": "NASストレージ N8",
     "manufacturer_model_number": "NAS-8B", "supplier": "日本サーバ販売",
     "major": "ストレージ", "mid": "NAS", "minor": "8ベイNAS",
     "standard_unit_price": 240000, "specs": "8ベイ / 最大128TB / 10GbE",
     "manual_ja": "RAID6推奨。バックアップ用途は別筐体での二重化を推奨。"},
    {"product_code": "UPS15", "product_name": "無停電電源 UPS15",
     "manufacturer_model_number": "UPS-1500", "supplier": "日本サーバ販売",
     "major": "ストレージ", "mid": "電源", "minor": "UPS",
     "standard_unit_price": 46000, "specs": "1500VA / ラックマウント対応",
     "manual_ja": "サーバー・NASの停電対策に。バッテリ寿命は約5年。"},
    # --- ネットワーク機器 -----------------------------------------------------
    {"product_code": "NSW24", "product_name": "ネットワークスイッチ 24p",
     "manufacturer_model_number": "NSW-24G", "supplier": "ネットワークス商会",
     "major": "ネットワーク機器", "mid": "スイッチ", "minor": "L2スイッチ",
     "standard_unit_price": 54000, "specs": "24ポート ギガビット / L2管理型",
     "manual_ja": "VLAN設定は管理画面から。PoEは非対応。"},
    {"product_code": "NSW48", "product_name": "ネットワークスイッチ 48p PoE",
     "manufacturer_model_number": "NSW-48P", "supplier": "ネットワークス商会",
     "major": "ネットワーク機器", "mid": "スイッチ", "minor": "L2 PoEスイッチ",
     "standard_unit_price": 128000, "specs": "48ポート / PoE+ / L2管理型",
     "manual_ja": "無線APやIP電話への給電に対応。総PoE電力に注意。"},
    {"product_code": "RTR10", "product_name": "VPNルーター R10",
     "manufacturer_model_number": "RTR-10V", "supplier": "ネットワークス商会",
     "major": "ネットワーク機器", "mid": "ルーター", "minor": "VPNルーター",
     "standard_unit_price": 38000, "specs": "IPsec/SSL-VPN / ギガ対応",
     "manual_ja": "拠点間VPNとリモートアクセスに対応。設定はテンプレ提供可。"},
    {"product_code": "WAP6", "product_name": "無線アクセスポイント W6",
     "manufacturer_model_number": "WAP-6AX", "supplier": "ネットワークス商会",
     "major": "ネットワーク機器", "mid": "無線", "minor": "無線AP",
     "standard_unit_price": 26000, "specs": "Wi-Fi6 / PoE給電 / 複数SSID",
     "manual_ja": "コントローラ不要のクラスタ運用に対応。"},
    {"product_code": "FW30", "product_name": "ファイアウォール F30",
     "manufacturer_model_number": "FW-30U", "supplier": "ネットワークス商会",
     "major": "ネットワーク機器", "mid": "セキュリティ機器", "minor": "UTM",
     "standard_unit_price": 145000, "specs": "UTM / IPS / アンチウイルス / 年間ライセンス別",
     "manual_ja": "年間更新ライセンスが必要。導入時にポリシー設計を推奨。"},
    # --- ソフトウェア ---------------------------------------------------------
    {"product_code": "OFFICE", "product_name": "オフィススイート(年間/席)",
     "manufacturer_model_number": "SW-OFFICE-Y", "supplier": "ソフト流通",
     "major": "ソフトウェア", "mid": "業務ソフト", "minor": "オフィススイート",
     "standard_unit_price": 13800, "specs": "文書/表計算/スライド + 1TB",
     "manual_ja": "ライセンスは即時発行。管理コンソールで一括割当可能。"},
    {"product_code": "AV365", "product_name": "エンドポイントセキュリティ(年間/席)",
     "manufacturer_model_number": "SW-EDR-Y", "supplier": "ソフト流通",
     "major": "ソフトウェア", "mid": "セキュリティ", "minor": "EDR",
     "standard_unit_price": 6800, "specs": "アンチウイルス + EDR / 1台",
     "manual_ja": "EDRログは90日保持。導入後の初回スキャンを推奨。"},
    {"product_code": "GRP50", "product_name": "グループウェア(年間/席)",
     "manufacturer_model_number": "SW-GRP-Y", "supplier": "ソフト流通",
     "major": "ソフトウェア", "mid": "業務ソフト", "minor": "グループウェア",
     "standard_unit_price": 9600, "specs": "スケジュール/ワークフロー/掲示板",
     "manual_ja": "既存メールと連携可。ワークフローは申請テンプレを提供。"},
    {"product_code": "BKP20", "product_name": "バックアップソフト(年間)",
     "manufacturer_model_number": "SW-BKP-Y", "supplier": "ソフト流通",
     "major": "ソフトウェア", "mid": "運用ソフト", "minor": "バックアップ",
     "standard_unit_price": 48000, "specs": "イメージ/ファイル / クラウド連携",
     "manual_ja": "世代管理とクラウド退避に対応。復旧手順書を同梱。"},
    {"product_code": "RPA30", "product_name": "RPAライセンス(年間)",
     "manufacturer_model_number": "SW-RPA-Y", "supplier": "ソフト流通",
     "major": "ソフトウェア", "mid": "業務自動化", "minor": "RPA",
     "standard_unit_price": 360000, "specs": "デスクトップ型 / ロボット1体",
     "manual_ja": "定型業務の自動化に。初期はシナリオ作成支援を推奨。"},
    {"product_code": "VPN50", "product_name": "リモートアクセス(年間/席)",
     "manufacturer_model_number": "SW-VPN-Y", "supplier": "ソフト流通",
     "major": "ソフトウェア", "mid": "セキュリティ", "minor": "リモートアクセス",
     "standard_unit_price": 4800, "specs": "ゼロトラスト型 / 多要素認証",
     "manual_ja": "テレワーク向け。多要素認証を標準で有効化。"},
    # --- 役務 / 保守 (services — booked as paid-service revenue) ---------------
    {"product_code": "SVCKIT", "product_name": "キッティングサービス",
     "manufacturer_model_number": "SVC-KIT", "supplier": "大塚商会SE",
     "major": "役務", "mid": "導入支援", "minor": "キッティング",
     "standard_unit_price": 8000, "specs": "PC1台あたりの初期設定・展開作業",
     "manual_ja": "資産管理エージェントの導入込み。台数で見積。"},
    {"product_code": "SVCONS", "product_name": "オンサイト保守(年間)",
     "manufacturer_model_number": "SVC-ONS", "supplier": "大塚商会SE",
     "major": "役務", "mid": "保守", "minor": "オンサイト保守",
     "standard_unit_price": 120000, "specs": "翌営業日訪問 / 年間契約",
     "manual_ja": "対象機器ごとに契約。SLAは翌営業日対応を基本とする。"},
    {"product_code": "SVCNET", "product_name": "ネットワーク構築サービス",
     "manufacturer_model_number": "SVC-NET", "supplier": "大塚商会SE",
     "major": "役務", "mid": "導入支援", "minor": "ネットワーク構築",
     "standard_unit_price": 180000, "specs": "現地調査 / 設計 / 構築 / 試験",
     "manual_ja": "現地調査を前提に見積。既存配線とVLAN要件を確認する。"},
]

# Company name parts for SMB customers (mostly no web presence). Each stem/suffix
# carries its romaji/English forms so customer_aliases.json can be auto-derived for
# every customer (English-input resolution in store.resolve_customer needs them).
_PREFIX = ["株式会社", "有限会社", ""]
_STEM: list[tuple[str, str]] = [
    ("山田", "Yamada"), ("あけぼの", "Akebono"), ("丸越", "Marukoshi"), ("大和", "Yamato"),
    ("みどり", "Midori"), ("東和", "Towa"), ("ヤマト", "Yamato"), ("富士", "Fuji"),
    ("明光", "Meiko"), ("サンライズ", "Sunrise"), ("第一", "Daiichi"), ("中央", "Chuo"),
    ("北斗", "Hokuto"), ("光", "Hikari"), ("新栄", "Shinei"), ("村田", "Murata"),
    ("小林", "Kobayashi"), ("石川", "Ishikawa"), ("ひかり", "Hikari"), ("あおぞら", "Aozora"),
    ("三幸", "Sanko"), ("ニュー", "New"), ("誠和", "Seiwa"), ("協和", "Kyowa"),
    ("宝", "Takara"), ("松田", "Matsuda"), ("森本", "Morimoto"), ("青木", "Aoki"),
    ("大東", "Daito"), ("昭和", "Showa"), ("平和", "Heiwa"), ("丸三", "Marusan"),
    ("旭", "Asahi"), ("瑞穂", "Mizuho"), ("豊田", "Toyoda"), ("長谷川", "Hasegawa"),
    ("江口", "Eguchi"), ("関東", "Kanto"), ("小島", "Kojima"),
    ("白井", "Shirai"), ("緑川", "Midorikawa"), ("黒田", "Kuroda"), ("今井", "Imai"),
    ("和田", "Wada"), ("藤本", "Fujimoto"), ("岡本", "Okamoto"), ("中島", "Nakajima"),
    ("西村", "Nishimura"), ("近藤", "Kondo"), ("遠藤", "Endo"),
]
_SUFFIX: list[tuple[str, list[str]]] = [
    ("商事", ["Shoji", "Trading"]),
    ("製作所", ["Seisakusho", "Works"]),
    ("工業", ["Kogyo", "Industries"]),
    ("システム", ["System", "Systems"]),
    ("物産", ["Bussan", "Trading"]),
    ("建設", ["Kensetsu", "Construction"]),
    ("サービス", ["Service", "Services"]),
    ("印刷", ["Insatsu", "Printing"]),
    ("運輸", ["Unyu", "Transport"]),
    ("電機", ["Denki", "Electric"]),
    ("クリニック", ["Clinic"]),
    ("事務所", ["Jimusho", "Office"]),
    ("食品", ["Shokuhin", "Foods"]),
    ("産業", ["Sangyo", "Industries"]),
    ("精工", ["Seiko", "Precision"]),
    ("興業", ["Kogyo", "Enterprise"]),
]
_INDUSTRY = ["製造", "小売", "医療", "建設", "飲食", "物流", "教育", "不動産", "士業", "IT"]
_SIZE = ["小規模", "小規模", "小規模", "中規模"]  # weighted toward SMB

# Anchor customers, keyed by the customer_id they must land on. These pin
# resolution-behavior fixtures the tests rely on:
#   · D001's customer must read 村田印刷 (asserted by a draft-message test).
#   · C28 is the Matsuda demo default.
#   · "Aozora Services" must resolve to exactly one customer (so the combo
#     あおぞら+サービス is reserved below — no random customer may reuse it).
#   · "Yamato Trading" must be ambiguous → two seeded customers both alias to it.
_FORCED_CUSTOMERS = {
    "C06": ("株式会社", ("あおぞら", "Aozora"), ("サービス", ["Service", "Services"])),
    "C07": ("株式会社", ("大和", "Yamato"), ("商事", ["Shoji", "Trading"])),
    "C13": ("有限会社", ("村田", "Murata"), ("印刷", ["Insatsu", "Printing"])),
    "C18": ("有限会社", ("ヤマト", "Yamato"), ("物産", ["Bussan", "Trading"])),
    "C28": ("株式会社", ("松田", "Matsuda"), ("サービス", ["Service", "Services"])),
}
# (stem_ja, suffix_ja) combos no random customer may use, so a reserved alias form
# stays uniquely resolvable (here: 'Aozora Services').
_RESERVED_COMBOS = {("あおぞら", "サービス")}
MURATA_CID = "C13"
MATSUDA_CID = "C28"

# Daily-report free text (the knowledge-mining corpus + stall detection source).
_REPORT_NORMAL = [
    "担当者と仕様を確認。前向きな反応。次回はデモを調整。",
    "見積を提出。社内で検討するとのこと。反応は良好。",
    "デモを実施。現場の評判は上々。導入後の運用を質問された。",
    "電話でフォロー。導入時期を相談。来月に再訪予定。",
    "競合製品と比較中とのこと。保守体制を強調して差別化を説明。",
    "現地調査を実施。既存環境の課題を整理して提案に反映する。",
    "担当者が上長に共有してくれた。次回は決裁者の同席を打診したい。",
    "追加要望をヒアリング。要件を精査して再見積を準備する。",
    "導入後の運用フローを説明。現場の不安が和らいだ様子。",
    "概算費用を提示。費用対効果の資料を追って送付する約束をした。",
    "他部署への横展開に関心あり。まずは今回の範囲で着実に進める。",
    "繁忙期を避けたいとのこと。スケジュールを調整して再提案する。",
]
_REPORT_STALL = [
    "担当者より「検討します」との返答。具体的な時期は未定。",
    "「予算が」厳しいとのことで保留。次年度予算を待つ流れ。",
    "「時期を見て」改めて相談したいとの回答。動きが鈍い。",
    "決裁は「上と相談」してから、と先送りに。決裁者は不明のまま。",
    "「持ち帰り」で社内調整するとのこと。以降の連絡が滞りがち。",
    "「また連絡します」と言われたきり、こちらからの追客に反応薄。",
    "他の優先案件が入り、今回は様子見との回答。停滞気味。",
]
# A few category-flavored normal reports, mixed in occasionally for variety.
_REPORT_BY_MAJOR = {
    "OA機器": ["複合機のランニングコストを試算して提示。トナー込み総額で比較したい意向。",
              "印刷枚数のカウンタを確認。現行機の保守切れ時期に合わせて提案する。"],
    "PC周辺機器": ["老朽PCの台数を棚卸し。キッティング込みの更新計画を提案する。",
                "リース満了の時期を確認。入替の段取りを早めに詰める。"],
    "サーバー": ["サーバー室の空調と電源を確認。設置要件を満たすか現地で精査する。",
              "現行サーバーの保守期限を確認。更改の必要性を数字で示す。"],
    "ストレージ": ["データ増加量をヒアリング。バックアップ含む容量設計を提案する。",
                "共有フォルダの運用課題を確認。NAS集約のメリットを説明。"],
    "ネットワーク機器": ["無線の電波状況を現地で確認。AP増設の必要性を提示。",
                    "拠点間の通信遅延を確認。VPN構成の見直しを提案する。"],
    "ソフトウェア": ["ライセンスの棚卸しを依頼。年間コストの最適化案を提示。",
                 "管理コンソールのデモを実施。一括運用の手間削減を訴求。"],
    "役務": ["現地調査の日程を調整。作業範囲とSLAを擦り合わせる。",
            "導入後の保守体制を説明。翌営業日対応の安心感を訴求。"],
}
_CHALLENGES = ["老朽化したPCの更新", "印刷コストの削減", "セキュリティ強化",
               "ネットワークの遅延", "サーバー更改", "業務効率化", "保守切れ対応",
               "テレワーク環境の整備", "データ容量の逼迫", "属人化した運用の標準化",
               "拠点間の情報共有", "バックアップ体制の見直し"]
_CARD_DM = ["情報システム部 部長", "総務部 課長", "代表取締役", "経営企画 本部長",
            "管理部 責任者", "取締役 管理本部長", "情シス長"]
_CARD_NONDM = ["情報システム部 担当", "総務部 担当者", "営業部 主任", "経理部 担当", ""]

# --- Skill-driven daily-report builder --------------------------------------
# Each fragment deliberately CARRIES the cue words of one Review Coach absence
# lens (see coach/review.py LENSES). A report includes a lens's sentence when the
# rep is strong on that dimension (and increasingly, over fiscal years, for
# "improving" reps) — and omits it when it's the rep's weakness. So a skilled rep
# produces a thorough note (few lenses fire) and a weak/early-career rep a thin one
# (many fire): the realistic spread the coach needs to not look gimmicky.
_BASE_SENT = ["担当者と仕様を確認。反応は前向き。",
              "現場の状況をヒアリングし、論点を整理した。",
              "製品の概要を説明し、関心を得た。",
              "既存環境を確認し、課題の当たりをつけた。"]
_LENS_SENT = {
    "decision_maker": ["決裁者は情報システム部の部長と確認できた。",
                       "稟議は部長決裁で進むと伺った。",
                       "意思決定は役員会で行うとのこと。"],
    "timeline": ["次回は来月初旬に再訪予定で日程を仮押さえした。",
                 "導入時期は月末までに決めたい意向。",
                 "社内検討は来週中にまとまる見込みと伺った。"],
    "criteria": ["判断基準は価格と保守体制を重視とのこと。",
                 "評価のポイントは運用負荷の軽さと実績。",
                 "比較の決め手はサポート品質との由。"],
    "next_step": ["次回はデモ資料を持参する宿題を設定した。",
                  "見積を提出し、次回打ち合わせを設定。",
                  "提案書を送付し再訪のアポを取得した。"],
    "budget": ["予算は確保済みで規模感も伺えた。",
               "費用感をすり合わせ、概算費用を提示した。",
               "今期予算で対応可能か金額を確認した。"],
}
_COMP_SENT = ["他社と価格を比較中とのこと。保守体制で差別化を説明した。",
              "競合製品と比較検討中。実績面の優位を訴求した。"]


def _build_report(lr, skill: dict, fy_off: int, dm_present: bool,
                  stall_latest: bool, comp: bool) -> str:
    """Compose a multi-sentence daily report whose lens-cue coverage reflects the
    rep's skill. `lr` is a LOCAL rng (keyed on the activity) so this never touches
    the main generation stream. `dm_present` ties the decision-maker sentence to
    the (already-resolved) business card. `fy_off` lets improving reps recover."""
    if stall_latest:
        return lr.choice(_REPORT_STALL)
    sents = [lr.choice(_BASE_SENT)]
    if dm_present:
        sents.append(lr.choice(_LENS_SENT["decision_maker"]))
    for theme in ("timeline", "criteria", "next_step", "budget"):
        if theme in skill["weaknesses"]:
            p = 0.12 + (0.20 * fy_off if skill["improving"] else 0.0)
        else:
            p = 0.85
        if lr.random() < min(p, 0.95):
            sents.append(lr.choice(_LENS_SENT[theme]))
    if comp:
        sents.append(lr.choice(_COMP_SENT))
    if "stall" in skill["weaknesses"] and lr.random() < 0.25:
        sents.append(lr.choice(_REPORT_STALL))
    return "".join(sents)

PLAYBOOK_SITUATIONS = [
    (["決定先延ばし", "クロージング"], "先延ばしには『次の一歩』を具体化する。次回訪問日とその場で決める事項を明確に提案する。"),
    (["予算", "価格"], "予算が理由の停滞は、年度末(3月)の予算消化タイミングを狙って再提案するのが有効。"),
    (["決裁者未特定", "提案"], "決裁者が見えない案件は、現場担当に『最終決定はどなたと進めますか』と早めに確認する。"),
    (["競合", "差別化"], "競合比較では保守体制と導入後のサポートを前面に。価格だけの勝負を避ける。"),
    (["複合機", "提案"], "複合機はランニングコスト(トナー・保守)込みの総額で比較表を作ると刺さる。"),
    (["ネットワーク", "導入"], "ネットワーク更改は現地調査を先に。既存配線とVLAN要件を押さえてから提案する。"),
    (["セキュリティ", "提案"], "セキュリティは『万一の事故コスト』を数字で示すと決裁が通りやすい。"),
    (["サーバー", "導入"], "サーバー導入は設置環境(ラック・空調・電源)の確認を提案前に済ませる。"),
    (["クラウド", "移行"], "クラウド移行は段階移行案を用意し、初期の不安を下げる。"),
    (["新規開拓", "アプローチ"], "Web情報の乏しいSMBは、近隣の同業導入事例を切り口にすると話が早い。"),
    (["保守", "更新"], "保守更新は満了3ヶ月前に接触。切替の手間より継続の安心を訴求。"),
    (["値引き", "交渉"], "値引き要求には台数増やオプション追加とセットで条件を返す。"),
    (["導入後", "フォロー"], "納品後2週間以内にフォロー訪問を入れると追加案件につながりやすい。"),
    (["決裁先送り", "稟議"], "稟議が止まる時は、決裁者向けの1枚要約(費用対効果)を担当者に渡す。"),
    (["飲食", "提案"], "飲食業はピーク時間を避けて訪問。短時間で要点を伝える資料を用意。"),
    (["医療", "提案"], "医療機関は個人情報保護の観点を最優先に説明すると信頼を得やすい。"),
    (["建設", "提案"], "建設業は現場とのネットワーク・モバイル環境の課題から入ると刺さる。"),
    (["小売", "提案"], "小売はPOS連携と複数店舗の一括管理を切り口にする。"),
    (["紹介", "拡大"], "満足度の高い顧客には同業他社の紹介を依頼。紹介は決裁が早い。"),
    (["失注", "再アプローチ"], "失注案件も半年後に状況が変わることが多い。定期的に軽く接触を続ける。"),
    (["初回訪問", "準備"], "初回は売り込まない。課題ヒアリングに徹し、次回の宿題をもらう。"),
    (["決裁者同席", "クロージング"], "最終局面は上長同席を打診し、その場で意思決定を促す。"),
    (["リプレース", "提案"], "更新案件は現行機の不満点を起点に、改善を具体的に見せる。"),
    (["コスト削減", "提案"], "コスト削減提案は年間総額の比較表を1枚にまとめる。"),
    (["スピード", "対応"], "SMBは即レス・即対応そのものが差別化になる。"),
    # --- appended for the broadened catalog ----------------------------------
    (["ストレージ", "提案"], "ストレージ提案はデータ増加量の実測から。3年後の容量を見込んで設計する。"),
    (["バックアップ", "提案"], "バックアップは『復旧できること』を訴求。リストア手順の実演が決め手になる。"),
    (["RPA", "業務効率化"], "RPAは小さな定型業務から着手。最初の1業務で効果を可視化すると横展開しやすい。"),
    (["役務", "保守"], "役務・保守はSLA(対応時間)を明確に。安さより『止まらない安心』を売る。"),
    (["テレワーク", "セキュリティ"], "テレワークは利便性と統制の両立を。多要素認証込みで提案すると決裁が通りやすい。"),
    (["UPS", "サーバー"], "サーバー・NASの提案には停電対策(UPS)を必ずセットで。事故時の損失で訴求する。"),
]


# --- Coaching threads (manager↔rep chat data) -------------------------------
# Short, templated manager↔rep exchanges raised on a flagged deal. They are the
# conversational/"chat" layer of the coaching product, and the resolved/open
# status (correlated with the rep's `improving` skill flag) gives the Phase-2
# progress tracker its "was the coaching acted on?" signal. Generated from a LOCAL
# rng so they never disturb the SPR tables.
_THREAD_TEXT = {
    "missing_decision_maker": {
        "manager": "{deal}、ランクの割に決裁者がまだ見えていないね。キーマンは誰か確認できてる?",
        "rep": "ご指摘ありがとうございます。現状は担当者どまりでした。次回、決裁ルートを確認します。",
        "resolved": "先方の情シス部長につないでいただけました。次回から同席いただけます。",
    },
    "long_inactivity": {
        "manager": "{deal}、しばらく動きが止まっているね。最後の接触から日が空いているけど状況は?",
        "rep": "失礼しました。先方の繁忙で間が空いていました。今週中にフォロー連絡を入れます。",
        "resolved": "再訪のアポを取得しました。来週打ち合わせを再開します。",
    },
    "weak_customer_discovery": {
        "manager": "{deal}、提案は出ているけど顧客の課題が日報に残っていないね。背景は掴めている?",
        "rep": "おっしゃる通り、課題のヒアリングが浅かったです。次回しっかり深掘りします。",
        "resolved": "現場の運用課題を整理できました。提案の軸を課題ベースに作り直します。",
    },
    "premature_discount": {
        "manager": "{deal}、価値が固まる前に値引きが先行していないか? 条件の出し方を相談しよう。",
        "rep": "確かに早めに値引きを提示していました。次回は台数増とセットで条件を組み直します。",
        "resolved": "値引きは保留し、保守込みの総額メリットで再提案して合意いただけました。",
    },
}


# Legacy-field maps: only used to populate backward-compat aliases on each deal so
# the friend-owned web-app/coach experiment (which reads d["stage"], d["amount"],
# etc.) keeps working. The canonical fields above mirror the real SPR schema.
_STAGE_FROM_RANK = {"6_P": "lead", "5_C": "qualified", "4_B": "proposal",
                    "3_A": "negotiation", "2_A+": "closing", "1_Confirmed": "closing",
                    "7_Lost": "lost", "8_Cancelled": "lost"}
_LIKELIHOOD_FROM_RANK = {"2_A+": "high", "3_A": "high", "1_Confirmed": "high",
                         "4_B": "med", "5_C": "low", "6_P": "low",
                         "7_Lost": "low", "8_Cancelled": "low"}

# Believable pipeline progression, strongest path (high rank-number → low number).
_PIPELINE_ORDER = ["6_P", "5_C", "4_B", "3_A", "2_A+", "1_Confirmed"]


def _split_revenue(amount: int, prod) -> tuple[int, int, int]:
    """Split a deal amount across hw/sw/paid buckets based on the product's major
    category, and return (hw, sw, paid)."""
    major = prod["major"]
    if major == "ソフトウェア":
        return 0, amount, 0
    if major == "役務":
        return 0, 0, amount                              # pure paid service
    if major in ("サーバー", "ストレージ", "ネットワーク機器"):
        return int(amount * 0.8), 0, int(amount * 0.2)   # some setup service
    return amount, 0, 0                                   # hardware (OA / PC)


def _rank_path(initial: str, final: str) -> list[str]:
    """A believable ordered list of ranks from `initial` to `final`.

    · strengthened (final is stronger/lower number): step down through the pipeline.
    · regressed (open deal dropped to a weaker rank): a single drop [initial, final].
    · dead (final is 7_Lost/8_Cancelled): [initial, final] (was live, then died).
    """
    if initial == final:
        return [initial]
    ni, nf = config.rank_num(initial), config.rank_num(final)
    if final in config.DEAD_RANKS or nf > ni:
        return [initial, final]
    # strengthened: every pipeline rank whose number is between final and initial.
    path = [r for r in _PIPELINE_ORDER if nf <= config.rank_num(r) <= ni]
    if initial not in path:
        path.insert(0, initial)
    if final not in path:
        path.append(final)
    return path


def _rank_history(initial: str, final: str, first_days_ago: int,
                  updated_days_ago: int) -> list[dict]:
    """Dated trail of order_rank changes (list of {rank, changed_at}). Oldest entry ==
    initial at the registration date; newest == final at rank_updated. Dates strictly
    increasing. Emitted to the separate rank_history.json table (additive — the scorer
    still reads only initial_order_rank + order_rank + rank_updated_at)."""
    path = _rank_path(initial, final)
    if first_days_ago == updated_days_ago:                   # registration == last touch
        return [{"rank": path[0], "changed_at": _iso(updated_days_ago)}]
    if len(path) == 1:                                       # rank never changed: span
        path = [path[0], path[0]]                            # registration → last touch
    k = len(path)
    span = first_days_ago - updated_days_ago                 # >0 (older → newer)
    hist = []
    for j, rank in enumerate(path):
        days_ago = round(first_days_ago - span * j / (k - 1))
        hist.append({"rank": rank, "changed_at": _iso(days_ago)})
    return hist


def _make_customers(rnd) -> tuple[list[dict], dict]:
    """~150 SMB customers + an auto-derived alias map (customer_aliases.json)."""
    customers: list[dict] = []
    aliases: dict[str, object] = {
        "_comment": ("English / romaji aliases per customer_id, auto-derived from the "
                     "name parts in gen_seed.py. Maps how a rep might type a customer "
                     "name in non-Japanese forms to the canonical JA record. Bare forms "
                     "only (no 株式会社/有限会社). Short stem forms (e.g. 'Yamato', "
                     "'Hikari') are intentionally shared across customers — the resolver "
                     "treats a name that matches >1 customer as ambiguous and refuses to "
                     "guess, so only specific forms ('Yamato Trading') resolve."),
    }
    seen: set[str] = set()
    n = 150
    for i in range(1, n + 1):
        cid = f"C{i:02d}"
        if cid in _FORCED_CUSTOMERS:
            prefix, (stem_ja, stem_ro), (suf_ja, suf_forms) = _FORCED_CUSTOMERS[cid]
        else:
            while True:
                prefix = rnd.choice(_PREFIX)
                stem_ja, stem_ro = rnd.choice(_STEM)
                suf_ja, suf_forms = rnd.choice(_SUFFIX)
                if (stem_ja, suf_ja) in _RESERVED_COMBOS:
                    continue
                if f"{prefix}{stem_ja}{suf_ja}" not in seen:
                    break
        name = f"{prefix}{stem_ja}{suf_ja}"
        seen.add(name)
        industry = rnd.choice(_INDUSTRY)
        customers.append({
            "customer_id": cid, "name": name, "industry": industry,
            "size": rnd.choice(_SIZE),
            "has_web_presence": rnd.random() < 0.25,   # ~75% SMB → mostly none
            "profile_tags": sorted({industry, rnd.choice(_SIZE),
                                    rnd.choice(["既存", "新規", "紹介"])}),
        })
        forms = [f"{stem_ro} {sf}" for sf in suf_forms]
        forms.append(stem_ro)
        aliases[cid] = sorted(dict.fromkeys(forms))        # dedupe, stable order
    return customers, aliases


def generate():
    rnd = random.Random(42)

    # --- customers + aliases ----------------------------------------------
    customers, customer_aliases = _make_customers(rnd)
    cust_by_id = {c["customer_id"]: c for c in customers}
    cust_ids = [c["customer_id"] for c in customers]
    emp_ids = [r["employee_id"] for r in REPS]

    # --- environments (GAP in SPR; supplementary, from another system) ------
    pcs = ["デスクトップ12台", "ノートPC8台", "デスクトップ5台/ノート3台", "ノートPC20台",
           "デスクトップ30台", "ノートPC15台/タブレット5台"]
    oses = ["Windows 11", "Windows 10", "Windows 10/11混在"]
    nets = ["光回線/無線LAN", "有線LANのみ", "光回線/VPN有", "ADSL(更改検討中)",
            "光回線/拠点間VPN"]
    env_notes = ["前任者からの引継ぎ情報。", "現地調査は未実施。",
                 "サーバー室の空調に余裕なし。", "プリンタは共有設定済み。",
                 "無線が一部届きにくいエリアあり。", "バックアップは外付けHDDのみ。"]
    environments = [{
        "customer_id": c["customer_id"], "pc": rnd.choice(pcs),
        "os": rnd.choice(oses), "network": rnd.choice(nets),
        "notes": rnd.choice(env_notes),
    } for c in customers]

    # --- deals + sales_activities + quotes + orders ------------------------
    deals, activities, quotes, orders = [], [], [], []
    rank_history = []                  # separate, normalized order-rank change log
    seqs = {"quote": 1, "order": 1}

    def add_deal(did, cid, emp, prod, qty, order_rank, initial_rank, cohort,
                 has_dm, stall):
        sales_info = next({"department": r["department"], "division": r["division"],
                           "employee_id": r["employee_id"]}
                          for r in REPS if r["employee_id"] == emp)
        amount = prod["standard_unit_price"] * qty
        confirmed = order_rank == "1_Confirmed"

        # --- cohort timing (days-ago from REF) -----------------------------
        if cohort == "dead_anchor":
            rank_updated = rnd.randint(50, 80)
            rank_first = rank_updated + rnd.randint(15, 40)
            last_activity = rnd.randint(45, 75)
            until_order = -rnd.randint(20, 35)            # already past
            status = "open"
        elif cohort == "live":
            rank_updated = rnd.randint(2, 40)
            rank_first = rank_updated + rnd.randint(10, 45)
            last_activity = rnd.randint(0, 25)
            until_order = rnd.randint(5, 70)
            status = "open"
        elif cohort == "won":
            rank_updated = rnd.randint(20, 760)           # confirmed across prior FYs
            rank_first = rank_updated + rnd.randint(25, 130)
            last_activity = rank_updated + rnd.randint(0, 12)
            until_order = -rank_updated + rnd.randint(-8, 8)   # order date ~ confirmation
            status = "won"
        else:  # "lost"
            rank_updated = rnd.randint(40, 760)
            rank_first = rank_updated + rnd.randint(25, 130)
            last_activity = rank_updated + rnd.randint(0, 20)
            until_order = -rnd.randint(5, max(6, rank_updated // 2))
            status = "lost"

        expected_order = _iso(-until_order)
        hw_o, sw_o, paid_o = _split_revenue(amount, prod)
        # gross profit ~22% hw, ~60% sw, ~35% paid service
        hw_gp, sw_gp, paid_gp = int(hw_o * 0.22), int(sw_o * 0.60), int(paid_o * 0.35)
        f = 1 if confirmed else 0                          # "actual" realised only if won
        deal = {
            "customer_id": cid, "deal_id": did, "sales_info": sales_info,
            "deal_name": f"{cust_by_id[cid]['name']} {prod['mid']}案件",
            "expected_order_date": expected_order,
            "days_until_order": until_order,
            "registered_at": _iso(rank_first + 5),
            "product_category": prod["major"],
            "hw_order_revenue": hw_o, "sw_order_revenue": sw_o, "paid_order_revenue": paid_o,
            "hw_order_gross_profit": hw_gp, "sw_order_gross_profit": sw_gp,
            "paid_order_gross_profit": paid_gp,
            "hw_actual_revenue": hw_o * f, "sw_actual_revenue": sw_o * f,
            "paid_actual_revenue": paid_o * f,
            "hw_actual_gross_profit": hw_gp * f, "sw_actual_gross_profit": sw_gp * f,
            "paid_actual_gross_profit": paid_gp * f,
            "total_order_amount": amount,
            "total_revenue": (hw_o + sw_o + paid_o) * f,
            "total_order_gross_profit": hw_gp + sw_gp + paid_gp,
            "total_revenue_gross_profit": (hw_gp + sw_gp + paid_gp) * f,
            "order_flag": amount > 0,
            "comment_count": rnd.randint(0, 12),
            "rank_first_registered_at": _iso(rank_first),
            "rank_updated_at": _iso(rank_updated),
            "order_rank": order_rank,
            "initial_order_rank": initial_rank,
            "days_back_from_confirmed": (until_order if confirmed else None),
        }
        # Backward-compat aliases (consumed only by the friend-owned experiment).
        deal.update({
            "rep_id": emp,
            "stage": _STAGE_FROM_RANK.get(order_rank, "lead"),
            "amount": amount,
            "status": status,
            "expected_close_date": expected_order,
            "close_date_history": [expected_order],
            "last_contact_date": _iso(last_activity),
            "decision_maker_identified": has_dm,
            "rep_close_likelihood": _LIKELIHOOD_FROM_RANK.get(order_rank, "low"),
            "stage_history": [{"stage": _STAGE_FROM_RANK.get(order_rank, "lead"),
                               "entered_date": _iso(rank_updated)}],
            "products": [prod["product_code"]],
        })
        deals.append(deal)

        # --- order-rank change log for this deal (separate supplementary table) ---
        for e in _rank_history(initial_rank, order_rank, rank_first, rank_updated):
            rank_history.append({"deal_id": did, "rank": e["rank"],
                                 "changed_at": e["changed_at"]})

        # --- sales_activities for this deal (the activity log / daily reports)
        oppid = "OPP" + did[1:]                            # 1:1 with deal here
        n_acts = rnd.randint(3, 6)
        emp_skill = REP_SKILL.get(emp, {"weaknesses": set(), "improving": False, "role": "junior"})
        for j in range(n_acts):
            latest = j == n_acts - 1
            adays = last_activity + (n_acts - 1 - j) * rnd.randint(6, 12)
            stall_latest = (cohort == "dead_anchor" or stall) and latest
            # Keep the ORIGINAL main-RNG draws (results discarded) so every amount/
            # rank/date downstream stays byte-identical; the skill-driven builder
            # below replaces only the text fields via a LOCAL rng.
            if stall_latest:
                _ = rnd.choice(_REPORT_STALL)
            elif rnd.random() < 0.3:
                _ = rnd.choice(_REPORT_BY_MAJOR.get(prod["major"], _REPORT_NORMAL))
            else:
                _ = rnd.choice(_REPORT_NORMAL)
            _ = rnd.choice(_CARD_DM) if has_dm else rnd.choice(_CARD_NONDM)
            atype = rnd.choice(["002_Daily Report", "002_Daily Report",
                                "001_Scheduled", "003_Deal", "004_Quote"])
            adate = _iso(adays)
            fy, fq = _fy(adate)
            # Keep the ORIGINAL draw ORDER (days_since, total_order_count, challenge)
            # so the main stream stays byte-identical — reordering changes values and
            # cascades into count-variable paths (n_acts, report branch length).
            dsl = rnd.randint(10, 400)
            toc = rnd.randint(0, 30)
            ch_main = rnd.choice(_CHALLENGES)
            # --- skill-driven enrichment (LOCAL rng → main stream untouched) ------
            lr = random.Random(f"act|{did}|{j}")
            fy_off = max(0, min(3, fy - 2023))
            recover = (0.20 * fy_off) if emp_skill["improving"] else 0.0
            dm_present = has_dm and not (
                "decision_maker" in emp_skill["weaknesses"] and lr.random() > recover)
            card = lr.choice(_CARD_DM) if dm_present else lr.choice(_CARD_NONDM)
            comp = lr.random() < 0.12
            text = _build_report(lr, emp_skill, fy_off, dm_present, stall_latest, comp)
            # discovery-weak reps leave the customer challenge blank more often;
            # improving reps recover this over fiscal years (the Phase-2 trend signal).
            blank_p = (0.6 - recover) if "discovery" in emp_skill["weaknesses"] else 0.0
            ch = "" if lr.random() < blank_p else ch_main
            activities.append({
                "customer_id": cid, "opportunity_id": oppid,
                "fiscal_year": fy, "fiscal_quarter": fq,
                "started_at": _iso(rank_first), "activity_date": adate,
                "closed_flag": status != "open",
                "activity_type": atype,
                "days_since_last_order": dsl,
                "total_order_count": toc,
                "sales_info": sales_info,
                "business_card_info": card,
                "product_major_category": prod["major"],
                "customer_challenge": ch,
                "daily_report": text,
                "quote_id": None, "order_id": None, "deal_id": did,
            })

        # --- quote (deals that progressed past prospecting get one) ----------
        if config.rank_num(initial_rank) <= 5 or confirmed:
            qid = f"Q{seqs['quote']:04d}"
            seqs["quote"] += 1
            disc_rate = rnd.choice([0, 5, 8, 10, 12])
            disc_amt = int(amount * disc_rate / 100)
            quotes.append({
                "quote_type": "Maintenance" if prod["major"] == "役務" else "Product Sales",
                "quote_id": qid,
                "quoted_at": _iso(rank_updated + 3),
                "quote_expiry_date": _iso(rank_updated + 3 - 30),
                "customer_id": cid, "sales_info": sales_info,
                "order_flag": "Confirmed" if confirmed else "Pending",
                "quote_amount": amount - disc_amt, "standard_amount": amount,
                "discount_amount": disc_amt, "discount_rate": disc_rate,
                "product_major_category": prod["major"],
                "product_mid_category": prod["mid"],
                "product_minor_category": prod["minor"],
                "similar_quote_count": rnd.randint(0, 9),
            })
            # link the most recent quote-type activity to this quote
            for a in reversed(activities):
                if a["deal_id"] == did and a["activity_type"] == "004_Quote":
                    a["quote_id"] = qid
                    break

            # --- order lines (only for confirmed/won deals) ------------------
            if confirmed:
                oid = f"O{seqs['order']:04d}"
                seqs["order"] += 1
                sell = (amount - disc_amt) // qty
                cogs = int(sell * 0.78)
                ordered = max(1, rank_updated - rnd.randint(0, 10))
                orders.append({
                    "customer_id": cid, "order_id": oid, "quote_id": qid,
                    "sales_info": sales_info,
                    "ordered_at": _iso(ordered), "shipped_at": _iso(max(0, ordered - 3)),
                    "shipping_duration": 3,
                    "total_sales_amount": amount - disc_amt, "cancellation_penalty": 0,
                    "product_code": prod["product_code"],
                    "manufacturer_model_number": prod["manufacturer_model_number"],
                    "product_name": prod["product_name"], "supplier": prod["supplier"],
                    "contract_unit_price": sell, "evaluated_unit_price": sell,
                    "standard_unit_price": prod["standard_unit_price"],
                    "selling_unit_price": sell, "cost_of_goods_sold": cogs * qty,
                    "gross_profit_amount": (sell - cogs) * qty,
                    "gross_profit_rate": round((sell - cogs) / sell * 100, 1) if sell else 0,
                    "discount_amount": disc_amt, "discount_rate": disc_rate,
                    "requested_quantity": qty,
                    "product_major_category": prod["major"],
                    "product_mid_category": prod["mid"],
                    "product_minor_category": prod["minor"],
                })
                for a in reversed(activities):
                    if a["deal_id"] == did:
                        a["order_id"] = oid
                        break

    # ----- cohort plan -----------------------------------------------------
    did_n = 1

    def next_did():
        nonlocal did_n
        d = f"D{did_n:03d}"
        did_n += 1
        return d

    # 1) Deliberately-dead anchors D001–D004: strong rank but stale, order date
    #    passed, no decision-maker. D001 is the 村田印刷 account.
    for k in range(4):
        cid = MURATA_CID if k == 0 else rnd.choice(cust_ids)
        rank = rnd.choice(["2_A+", "3_A"])
        add_deal(next_did(), cid, rnd.choice(emp_ids), rnd.choice(PRODUCTS),
                 rnd.randint(1, 6), rank, rank, "dead_anchor", has_dm=False, stall=True)

    # 2) Matsuda (C28) rich open pipeline — varied ranks/health for the demo Q&A.
    matsuda_plan = [
        ("2_A+", False, True), ("3_A", True, False), ("4_B", True, False),
        ("5_C", False, True), ("6_P", True, False),
    ]
    matsuda_emps = ["R05", "R01", "R02", "R05", "R03"]
    for (rank, has_dm, stall), emp in zip(matsuda_plan, matsuda_emps):
        add_deal(next_did(), MATSUDA_CID, emp, rnd.choice(PRODUCTS), rnd.randint(1, 6),
                 rank, rank, "live", has_dm=has_dm, stall=stall)

    # 3) General live pipeline (open ranks, near REF).
    for _ in range(131):
        order_rank = rnd.choices(["2_A+", "3_A", "4_B", "5_C", "6_P"],
                                 weights=[10, 18, 22, 20, 14])[0]
        initial_rank = order_rank
        if rnd.random() < 0.3:                             # ~30% honestly regressed
            stronger = [r for r in ["2_A+", "3_A", "4_B"]
                        if config.rank_num(r) < config.rank_num(order_rank)]
            if stronger:
                initial_rank = rnd.choice(stronger)
        add_deal(next_did(), rnd.choice(cust_ids), rnd.choice(emp_ids),
                 rnd.choice(PRODUCTS), rnd.randint(1, 6), order_rank, initial_rank,
                 "live", has_dm=rnd.random() < 0.6, stall=rnd.random() < 0.2)

    # 4) Historical won (1_Confirmed) across prior fiscal years.
    for _ in range(280):
        initial_rank = rnd.choice(["3_A", "4_B", "4_B", "5_C"])
        add_deal(next_did(), rnd.choice(cust_ids), rnd.choice(emp_ids),
                 rnd.choice(PRODUCTS), rnd.randint(1, 6), "1_Confirmed", initial_rank,
                 "won", has_dm=rnd.random() < 0.85, stall=False)

    # 5) Historical dead (7_Lost / 8_Cancelled).
    for _ in range(100):
        order_rank = rnd.choices(["7_Lost", "8_Cancelled"], weights=[80, 20])[0]
        initial_rank = rnd.choice(["3_A", "4_B", "5_C", "6_P"])
        add_deal(next_did(), rnd.choice(cust_ids), rnd.choice(emp_ids),
                 rnd.choice(PRODUCTS), rnd.randint(1, 6), order_rank, initial_rank,
                 "lost", has_dm=rnd.random() < 0.4, stall=rnd.random() < 0.5)

    # --- playbook (mined-from-daily_report knowledge artifact) -------------
    playbook = []
    for k, (tags, text) in enumerate(PLAYBOOK_SITUATIONS):
        author = rnd.choice([r for r in REPS if r["role"] in ("senior", "expert")])
        playbook.append({
            "entry_id": f"PB{k + 1:02d}", "situation_tags": tags, "text": text,
            "source_deal_id": rnd.choice([d["deal_id"] for d in deals]),
            "author_rep_id": author["employee_id"],
        })

    coaching_threads = _make_coaching_threads(deals, activities, quotes, orders)

    return {
        # supplementary reference data
        "reps": REPS, "customers": customers, "products": PRODUCTS,
        "environments": environments, "playbook": playbook,
        "customer_aliases": customer_aliases, "rank_history": rank_history,
        "coaching_threads": coaching_threads,
        # production SPR schema tables
        "deals": deals, "sales_activities": activities,
        "quotes": quotes, "orders": orders,
    }


def _make_coaching_threads(deals, activities, quotes, orders) -> list[dict]:
    """Deterministic manager↔rep coaching threads raised on flagged OPEN deals.

    Uses a LOCAL rng so the SPR tables stay byte-identical. The thread's resolved/
    open status is correlated with the owning rep's `improving` flag, giving the
    Phase-2 progress tracker a real 'was the coaching acted on?' signal."""
    lr = random.Random("coaching_threads_v1")
    by_deal: dict[str, list[dict]] = {}
    for a in activities:
        by_deal.setdefault(a["deal_id"], []).append(a)
    q_disc = {q["quote_id"]: (q.get("discount_rate") or 0) for q in quotes}
    o_disc = {o["order_id"]: (o.get("discount_rate") or 0) for o in orders}
    mgrs_by_dept: dict[str, list[str]] = {}
    for r in REPS:
        if r["role"] in ("senior", "expert"):
            mgrs_by_dept.setdefault(r["department"], []).append(r["employee_id"])

    def _has_dm(acts):
        return any(any(t in (a.get("business_card_info") or "")
                       for t in config.DECISION_MAKER_TITLES) for a in acts)

    threads: list[dict] = []
    tid = 1
    for d in sorted(deals, key=lambda x: x["deal_id"]):
        rank = d.get("order_rank")
        if rank not in config.OPEN_RANKS:
            continue
        acts = by_deal.get(d["deal_id"], [])
        if not acts:
            continue
        emp = d["sales_info"]["employee_id"]
        skill = REP_SKILL.get(emp, {"improving": False})
        has_dm = _has_dm(acts)
        last = max(a["activity_date"] for a in acts)
        days_inactive = (REF - date.fromisoformat(last)).days
        filled = sum(1 for a in acts if a.get("customer_challenge"))
        disc = 0
        for a in acts:
            if a.get("quote_id"):
                disc = max(disc, q_disc.get(a["quote_id"], 0))
            if a.get("order_id"):
                disc = max(disc, o_disc.get(a["order_id"], 0))
        # collect ALL applicable issues, then pick one (variety across the team)
        applicable = []
        if rank in config.DECISION_MAKER_RANKS and not has_dm:
            applicable.append("missing_decision_maker")
        if days_inactive > 30:
            applicable.append("long_inactivity")
        if len(acts) >= 3 and filled / len(acts) < 0.34:
            applicable.append("weak_customer_discovery")
        if disc > 10 and (not has_dm or config.rank_num(rank) >= 4):
            applicable.append("premature_discount")
        if not applicable:
            continue
        if lr.random() > 0.7:            # thread a subset of flagged deals
            continue
        issue = lr.choice(applicable)

        mgrs = [m for m in mgrs_by_dept.get(d["sales_info"]["department"], []) if m != emp]
        manager_id = lr.choice(mgrs) if mgrs else "R01"
        tpl = _THREAD_TEXT[issue]
        created = min(max(days_inactive + lr.randint(2, 10), 1), 360)
        if skill.get("improving") and lr.random() < 0.7:
            status = "resolved"
        elif lr.random() < 0.5:
            status = "acknowledged"
        else:
            status = "open"
        messages = [
            {"role": "manager", "author_id": manager_id, "date": _iso(created),
             "text": tpl["manager"].format(deal=d["deal_id"])},
            {"role": "rep", "author_id": emp, "date": _iso(created - 1),
             "text": tpl["rep"]},
        ]
        if status == "resolved":
            messages.append({"role": "rep", "author_id": emp, "date": _iso(max(created - 4, 1)),
                             "text": tpl["resolved"]})
        threads.append({
            "thread_id": f"CT{tid:04d}", "deal_id": d["deal_id"],
            "employee_id": emp, "manager_id": manager_id, "issue_key": issue,
            "created_at": _iso(created), "status": status, "messages": messages,
        })
        tid += 1
    return threads


def write():
    config.SEED_DIR.mkdir(parents=True, exist_ok=True)
    data = generate()
    for name, rows in data.items():
        path = config.SEED_DIR / f"{name}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        n = len(rows) if isinstance(rows, list) else len(rows) - 1   # alias map: minus _comment
        print(f"wrote {path.relative_to(config.PKG_DIR.parent)} ({n} rows)")


if __name__ == "__main__":
    write()
