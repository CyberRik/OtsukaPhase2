"""Multimodal Data Ingestion Pipeline for Senpai.

This module handles ingestion from various multimodal sources (audio voice notes,
images of business cards, etc.) and transforms them into the structured
`sales_activities` schema required by Senpai's deterministic engine.

Features:
- Audio Processing (Voice to Text via Whisper)
- Image Processing (OCR / Vision models for business cards/whiteboards)
- Structured Data Extraction (LLM -> JSON schema matching sales_activities)
"""
from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from senpai import config
from senpai.data import store
from senpai.llm.client import simple_complete

# ---------------------------------------------------------------------------
# Schema Definitions (Mirroring `sales_activities.json` expectations)
# ---------------------------------------------------------------------------

class ActivityExtraction(BaseModel):
    """The structured output format expected from the LLM extraction step."""
    activity_type: Literal[
        "001_Scheduled", "002_Daily Report", "003_Deal", "004_Quote", 
        "005_Order", "006_Maintenance Quote", "007_Maintenance Contract", 
        "008_Contract Billing", "901_Auto-Scheduled"
    ] = Field(description="The category of the sales activity.")
    business_card_info: str = Field(
        default="", 
        description="Titles, roles, and names of contacts extracted (e.g. '情報システム部 部長')."
    )
    product_major_category: str = Field(
        default="", 
        description="Top-level product category discussed (e.g. 'PC周辺機器', 'モバイル', 'サーバ')."
    )
    customer_challenge: str = Field(
        default="", 
        description="The customer's pain point or challenge (e.g. '業務効率化', 'コスト削減')."
    )
    daily_report: str = Field(
        default="", 
        description="The detailed note/summary of the interaction, in Japanese."
    )


# ---------------------------------------------------------------------------
# Pipeline Implementation
# ---------------------------------------------------------------------------

class MultimodalIngestor:
    """Orchestrates the ingestion, transcription, OCR, and extraction of data."""
    
    def process_audio(self, file_path: str) -> str:
        """Mock Audio Transcription.
        
        In production, this would call `client.audio.transcriptions.create(model="whisper-1", file=...)`
        """
        print(f"🎙️ [Ingestion] Transcribing audio file: {file_path}")
        # MOCK: Pretend we used Whisper on a voice note.
        return "えー、今日アクメ商事さんを訪問しました。情報システム部の鈴木部長とお話しして、モバイル端末の導入について提案しました。課題としてはテレワーク環境のセキュリティ強化だそうです。反応は悪くないですが、予算取りで少し検討が必要とのことでした。"

    def process_image(self, file_path: str) -> str:
        """Mock Image OCR / Vision Extraction.
        
        In production, this would call `client.chat.completions.create` with `gpt-4o` 
        and the base64 encoded image, asking it to extract all text.
        """
        print(f"📸 [Ingestion] Extracting text/context from image: {file_path}")
        # MOCK: Pretend we snapped a photo of a business card + whiteboard.
        return "名刺抽出: アクメ商事株式会社 情報システム部 部長 鈴木一郎\nメモ: テレワーク、セキュリティ、モバイル"

    def extract_activity(self, raw_text: str) -> ActivityExtraction:
        """Uses the Senpai LLM client to extract structured fields from raw text."""
        system_prompt = (
            "You are a sales operations assistant. Extract structured sales activity data "
            "from the following raw text (which may be a transcribed voice note or OCR output). "
            "Output strictly in JSON format matching the requested schema. "
            "Do not invent information. If a field is not mentioned, leave it empty."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Extract JSON from this raw text:\n\n{raw_text}"}
        ]
        
        # We append a format instruction. In a real environment with GPT-4 we'd use
        # response_format={"type": "json_object"}, but for local Qwen/exp3 we instruct strongly.
        schema_json = json.dumps(ActivityExtraction.model_json_schema(), ensure_ascii=False, indent=2)
        messages[1]["content"] += f"\n\nOutput ONLY a JSON object that satisfies this schema:\n{schema_json}"
        
        print("🧠 [Ingestion] Extracting structured data using LLM...")
        raw_response = simple_complete(messages, temperature=0.1, no_think=True)
        
        # Basic JSON extraction to handle markdown blocks
        json_str = raw_response
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
            
        try:
            data = json.loads(json_str.strip())
            return ActivityExtraction(**data)
        except Exception as e:
            print(f"⚠️ [Ingestion] Failed to parse LLM output: {e}\nRaw output: {raw_response}")
            # Fallback
            return ActivityExtraction(
                activity_type="002_Daily Report",
                daily_report=raw_text
            )

    def ingest_to_store(
        self, 
        customer_id: str, 
        deal_id: str, 
        employee_id: str, 
        extraction: ActivityExtraction
    ) -> dict:
        """Maps the extracted data to the full schema and appends to the store."""
        # Find opportunity/deal info to fill out required fields
        deal = store.get_deal(deal_id)
        opp_id = deal.get("opportunity_id", "OPP_UNKNOWN") if deal else "OPP_UNKNOWN"
        
        # Build the final activity record
        activity_record = {
            "customer_id": customer_id,
            "opportunity_id": opp_id,
            "fiscal_year": config.today().year,
            "fiscal_quarter": (config.today().month - 1) // 3 + 1,
            "started_at": deal.get("registered_at", config.today().isoformat()) if deal else config.today().isoformat(),
            "activity_date": config.today().isoformat(),
            "closed_flag": False,
            "activity_type": extraction.activity_type,
            "days_since_last_order": 0,  # Would be calculated in a real DB
            "total_order_count": 0,
            "sales_info": {
                "department": "営業部",  # Mocked
                "division": "1課",
                "employee_id": employee_id
            },
            "business_card_info": extraction.business_card_info,
            "product_major_category": extraction.product_major_category,
            "customer_challenge": extraction.customer_challenge,
            "daily_report": extraction.daily_report,
            "quote_id": None,
            "order_id": None,
            "deal_id": deal_id
        }
        
        print(f"💾 [Ingestion] Saving new activity to store for Deal {deal_id}")
        store.all_activities().append(activity_record)
        return activity_record


# ---------------------------------------------------------------------------
# Simple Demo Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import pprint
    ingestor = MultimodalIngestor()
    
    print("\n--- Testing Voice Ingestion ---")
    raw_audio_text = ingestor.process_audio("voice_memo_001.m4a")
    extracted_data = ingestor.extract_activity(raw_audio_text)
    record = ingestor.ingest_to_store(
        customer_id="C13", deal_id="D001", employee_id="R12", extraction=extracted_data
    )
    pprint.pprint(record)
