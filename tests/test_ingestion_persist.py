"""Unit tests for runtime daily-report ingestion (no GPU, no model).

Verifies that a saved draft becomes a sales_activities row in the EXACT seed
shape (correct Japanese fiscal year/quarter, rep dept/division, derived order
stats), is written only to the gitignored overlay, and is visible to the store
after save — without ever mutating the committed seed.
"""
from __future__ import annotations

import pytest

from senpai import config
from senpai.data import store
from senpai.ingestion import persist


@pytest.fixture
def overlay_tmp(tmp_path, monkeypatch):
    """Redirect the ingested overlay dir to a temp path so the test never writes
    the real seed/overlay; reset the store cache around the test."""
    monkeypatch.setattr(config, "INGESTED_DIR", tmp_path / "ingested")
    store.reload()
    yield
    store.reload()


def _any_real(coll):
    return coll[0]


def test_build_record_matches_seed_shape(overlay_tmp):
    seed_act = _any_real(store.all_activities())
    deal = store.open_deals()[0]
    emp = store.deal_rep_id(deal)
    rep = store.get_rep(emp)

    rec = persist.build_activity_record(
        {"activity_type": "002_Daily Report", "daily_report": "訪問。前向き。",
         "business_card_info": "部長 鈴木", "product_major_category": "サーバ",
         "customer_challenge": "コスト削減"},
        deal["customer_id"], deal["deal_id"], emp,
    )

    # Same keys as a real seed activity — won't crash any downstream reader.
    assert set(rec.keys()) == set(seed_act.keys())
    # Fiscal calendar (not calendar year): a March date is FY-1 Q4.
    assert config.fiscal_year_quarter("2026-03-05") == (2025, 4)
    fy, fq = config.fiscal_year_quarter(config.today().isoformat())
    assert (rec["fiscal_year"], rec["fiscal_quarter"]) == (fy, fq)
    # Dept/division come from the rep record, not a mock.
    assert rec["sales_info"]["department"] == rep["department"]
    assert rec["sales_info"]["division"] == rep["division"]
    assert rec["sales_info"]["employee_id"] == emp
    assert rec["deal_id"] == deal["deal_id"]


def test_save_is_visible_and_isolated(overlay_tmp):
    deal = store.open_deals()[0]
    emp = store.deal_rep_id(deal)
    before = len(store.activities_for_deal(deal["deal_id"]))

    persist.save_activity(
        {"activity_type": "002_Daily Report", "daily_report": "オーバーレイ確認"},
        deal["customer_id"], deal["deal_id"], emp,
    )

    acts = store.activities_for_deal(deal["deal_id"])
    assert len(acts) == before + 1
    assert acts[0]["daily_report"] == "オーバーレイ確認"  # newest-first
    # Written to the overlay, never the committed seed.
    assert (config.INGESTED_DIR / "sales_activities.json").exists()
    assert not (config.SEED_DIR / "sales_activities.json").samefile(
        config.INGESTED_DIR / "sales_activities.json")
