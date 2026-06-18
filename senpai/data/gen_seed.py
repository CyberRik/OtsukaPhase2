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

Content is Japanese (data) to match the Otsuka context; field names stay English.
A handful of deals are deliberately authored as dead/dying — strong rank but stale,
past their order date, no decision-maker — so the manager view flags real risk on
first load (and the optimism-mismatch flag fires).
"""
from __future__ import annotations

import json
import random
from datetime import timedelta

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
]

# Product master. major/mid/minor mirror the orders/quotes category columns.
PRODUCTS = [
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
    {"product_code": "LP14", "product_name": "ノートPro 14",
     "manufacturer_model_number": "NB-PRO-14", "supplier": "東京電子",
     "major": "PC周辺機器", "mid": "モバイル端末", "minor": "ノートPC",
     "standard_unit_price": 168000, "specs": "14型 / Core i7 / 16GB / 512GB SSD",
     "manual_ja": "法人向けキッティング対応。3年保証オプションあり。"},
    {"product_code": "SRV20", "product_name": "ラックサーバー R20",
     "manufacturer_model_number": "SRV-R20", "supplier": "日本サーバ販売",
     "major": "サーバー", "mid": "ラックサーバー", "minor": "1Uサーバー",
     "standard_unit_price": 520000, "specs": "1U / Xeon / 64GB / NVMe x2",
     "manual_ja": "RAID1構成を推奨。設置にはラックと空調の確認が必要。"},
    {"product_code": "NSW24", "product_name": "ネットワークスイッチ 24p",
     "manufacturer_model_number": "NSW-24G", "supplier": "ネットワークス商会",
     "major": "ネットワーク機器", "mid": "スイッチ", "minor": "L2スイッチ",
     "standard_unit_price": 54000, "specs": "24ポート ギガビット / L2管理型",
     "manual_ja": "VLAN設定は管理画面から。PoEは非対応。"},
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
]

# Company name parts for SMB customers (mostly no web presence).
_PREFIX = ["株式会社", "有限会社", ""]
_STEM = ["山田", "あけぼの", "丸越", "大和", "みどり", "東和", "ヤマト", "富士", "明光",
         "サンライズ", "第一", "中央", "北斗", "光", "新栄", "村田", "小林", "石川",
         "ひかり", "あおぞら", "三幸", "ニュー", "誠和", "協和", "宝", "松田", "森本"]
_SUFFIX = ["商事", "製作所", "工業", "システム", "物産", "建設", "サービス", "印刷",
           "運輸", "電機", "クリニック", "事務所", "食品", "産業"]
_INDUSTRY = ["製造", "小売", "医療", "建設", "飲食", "物流", "教育", "不動産", "士業", "IT"]
_SIZE = ["小規模", "小規模", "小規模", "中規模"]  # weighted toward SMB

# Daily-report free text (the knowledge-mining corpus + stall detection source).
_REPORT_NORMAL = [
    "担当者と仕様を確認。前向きな反応。次回はデモを調整。",
    "見積を提出。社内で検討するとのこと。反応は良好。",
    "デモを実施。現場の評判は上々。導入後の運用を質問された。",
    "電話でフォロー。導入時期を相談。来月に再訪予定。",
    "競合製品と比較中とのこと。保守体制を強調して差別化を説明。",
    "現地調査を実施。既存環境の課題を整理して提案に反映する。",
]
_REPORT_STALL = [
    "担当者より「検討します」との返答。具体的な時期は未定。",
    "「予算が」厳しいとのことで保留。次年度予算を待つ流れ。",
    "「時期を見て」改めて相談したいとの回答。動きが鈍い。",
    "決裁は「上と相談」してから、と先送りに。決裁者は不明のまま。",
]
_CHALLENGES = ["老朽化したPCの更新", "印刷コストの削減", "セキュリティ強化",
               "ネットワークの遅延", "サーバー更改", "業務効率化", "保守切れ対応",
               "テレワーク環境の整備"]
_CARD_DM = ["情報システム部 部長", "総務部 課長", "代表取締役", "経営企画 本部長",
            "管理部 責任者"]
_CARD_NONDM = ["情報システム部 担当", "総務部 担当者", "営業部 主任", ""]

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
]


def _company_name(rnd):
    return f"{rnd.choice(_PREFIX)}{rnd.choice(_STEM)}{rnd.choice(_SUFFIX)}"


def _split_revenue(amount: int, prod):
    """Split a deal amount across hw/sw/paid buckets based on the product's major
    category, and return (hw, sw, paid)."""
    major = prod["major"]
    if major == "ソフトウェア":
        return 0, amount, 0
    if major in ("サーバー", "ネットワーク機器"):
        return int(amount * 0.8), 0, int(amount * 0.2)   # some setup service
    return amount, 0, 0                                   # hardware


def generate():
    rnd = random.Random(42)

    # --- customers ---------------------------------------------------------
    customers, seen = [], set()
    while len(customers) < 35:
        name = _company_name(rnd)
        if name in seen:
            continue
        seen.add(name)
        cid = f"C{len(customers) + 1:02d}"
        industry = rnd.choice(_INDUSTRY)
        customers.append({
            "customer_id": cid, "name": name, "industry": industry,
            "size": rnd.choice(_SIZE),
            "has_web_presence": rnd.random() < 0.25,   # ~78% SMB → mostly none
            "profile_tags": sorted({industry, rnd.choice(_SIZE),
                                    rnd.choice(["既存", "新規", "紹介"])}),
        })

    # --- environments (GAP in SPR; supplementary, from another system) ------
    pcs = ["デスクトップ12台", "ノートPC8台", "デスクトップ5台/ノート3台", "ノートPC20台"]
    oses = ["Windows 11", "Windows 10", "Windows 10/11混在"]
    nets = ["光回線/無線LAN", "有線LANのみ", "光回線/VPN有", "ADSL(更改検討中)"]
    env_notes = ["前任者からの引継ぎ情報。", "現地調査は未実施。",
                 "サーバー室の空調に余裕なし。", "プリンタは共有設定済み。"]
    environments = [{
        "customer_id": c["customer_id"], "pc": rnd.choice(pcs),
        "os": rnd.choice(oses), "network": rnd.choice(nets),
        "notes": rnd.choice(env_notes),
    } for c in customers]

    # --- deals + sales_activities + quotes + orders ------------------------
    deals, activities, quotes, orders = [], [], [], []
    cust_ids = [c["customer_id"] for c in customers]
    emp_ids = [r["employee_id"] for r in REPS]
    act_seq = quote_seq = order_seq = 1

    DEAD_COUNT, TOTAL = 4, 60

    for i in range(TOTAL):
        did = f"D{i + 1:03d}"
        oppid = f"OPP{i + 1:03d}"           # 1:1 with deal in this synthetic set
        cid = rnd.choice(cust_ids)
        emp = rnd.choice(emp_ids)
        sales_info = next({"department": r["department"], "division": r["division"],
                           "employee_id": r["employee_id"]} for r in REPS if r["employee_id"] == emp)
        prod = rnd.choice(PRODUCTS)
        qty = rnd.randint(1, 6)
        amount = prod["standard_unit_price"] * qty
        is_dead = i < DEAD_COUNT

        if is_dead:
            # Strong rank (rep optimism) but stale, order date passed, no DM.
            order_rank = rnd.choice(["2_A+", "3_A"])
            initial_rank = order_rank                 # rep never downgraded it
            rank_updated = rnd.randint(50, 80)
            last_activity = rnd.randint(45, 75)
            until_order = -rnd.randint(20, 35)        # already past
            has_dm = False
            stall = True
            status = "open"
        else:
            order_rank = rnd.choices(
                ["2_A+", "3_A", "4_B", "5_C", "6_P", "1_Confirmed", "7_Lost"],
                weights=[8, 14, 16, 14, 10, 18, 10])[0]
            # ~30% of open deals honestly regressed to a weaker rank.
            initial_rank = order_rank
            if config.is_open_rank(order_rank) and rnd.random() < 0.3:
                stronger = [r for r in ["2_A+", "3_A", "4_B"]
                            if config.rank_num(r) < config.rank_num(order_rank)]
                if stronger:
                    initial_rank = rnd.choice(stronger)
            rank_updated = rnd.randint(2, 40)
            last_activity = rnd.randint(0, 25)
            until_order = rnd.randint(5, 70)
            has_dm = rnd.random() < 0.6
            stall = rnd.random() < 0.2
            status = ("won" if order_rank == "1_Confirmed"
                      else "lost" if order_rank == "7_Lost" else "open")

        rank_first = rank_updated + rnd.randint(5, 30)
        expected_order = _iso(-until_order)
        confirmed = order_rank == "1_Confirmed"

        hw_o, sw_o, paid_o = _split_revenue(amount, prod)
        # gross profit ~22% hw, ~60% sw, ~35% paid service
        hw_gp, sw_gp, paid_gp = int(hw_o * 0.22), int(sw_o * 0.60), int(paid_o * 0.35)
        # "actual" revenue is realised only once confirmed.
        f = 1 if confirmed else 0
        deal = {
            "customer_id": cid, "deal_id": did, "sales_info": sales_info,
            "deal_name": f"{customers[int(cid[1:]) - 1]['name']} {prod['mid']}案件",
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
        deals.append(deal)

        # --- sales_activities for this deal (the activity log / daily reports)
        n_acts = rnd.randint(2, 4)
        fy, fq = _fy(_iso(rank_first))
        for j in range(n_acts):
            latest = j == n_acts - 1
            adays = last_activity + (n_acts - 1 - j) * rnd.randint(6, 12)
            if is_dead and latest:
                text = rnd.choice(_REPORT_STALL)
            elif stall and latest:
                text = rnd.choice(_REPORT_STALL)
            else:
                text = rnd.choice(_REPORT_NORMAL)
            card = (rnd.choice(_CARD_DM) if has_dm else rnd.choice(_CARD_NONDM))
            atype = rnd.choice(["002_Daily Report", "002_Daily Report",
                                "001_Scheduled", "003_Deal", "004_Quote"])
            activities.append({
                "customer_id": cid, "opportunity_id": oppid,
                "fiscal_year": fy, "fiscal_quarter": fq,
                "started_at": _iso(rank_first), "activity_date": _iso(adays),
                "closed_flag": status != "open",
                "activity_type": atype,
                "days_since_last_order": rnd.randint(10, 400),
                "total_order_count": rnd.randint(0, 30),
                "sales_info": sales_info,
                "business_card_info": card,
                "product_major_category": prod["major"],
                "customer_challenge": rnd.choice(_CHALLENGES),
                "daily_report": text,
                "quote_id": None, "order_id": None, "deal_id": did,
            })
            act_seq += 1

        # --- quote (deals that progressed past prospecting get one) ----------
        if config.rank_num(order_rank) <= 5 or confirmed:
            qid = f"Q{quote_seq:04d}"
            quote_seq += 1
            disc_rate = rnd.choice([0, 5, 8, 10, 12])
            disc_amt = int(amount * disc_rate / 100)
            quotes.append({
                "quote_type": "Product Sales", "quote_id": qid,
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

            # --- order lines (only for confirmed deals) ----------------------
            if confirmed:
                oid = f"O{order_seq:04d}"
                order_seq += 1
                sell = (amount - disc_amt) // qty
                cogs = int(sell * 0.78)
                ordered = rnd.randint(1, 20)
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

    # --- playbook (mined-from-daily_report knowledge artifact) -------------
    playbook = []
    for k, (tags, text) in enumerate(PLAYBOOK_SITUATIONS):
        author = rnd.choice([r for r in REPS if r["role"] in ("senior", "expert")])
        playbook.append({
            "entry_id": f"PB{k + 1:02d}", "situation_tags": tags, "text": text,
            "source_deal_id": rnd.choice([d["deal_id"] for d in deals]),
            "author_rep_id": author["employee_id"],
        })

    return {
        # supplementary reference data
        "reps": REPS, "customers": customers, "products": PRODUCTS,
        "environments": environments, "playbook": playbook,
        # production SPR schema tables
        "deals": deals, "sales_activities": activities,
        "quotes": quotes, "orders": orders,
    }


def write():
    config.SEED_DIR.mkdir(parents=True, exist_ok=True)
    data = generate()
    for name, rows in data.items():
        path = config.SEED_DIR / f"{name}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(f"wrote {path.relative_to(config.PKG_DIR.parent)} ({len(rows)} rows)")


if __name__ == "__main__":
    write()
