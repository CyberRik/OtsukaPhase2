"""Standalone Multimodal Data Ingestion CLI.

This module processes raw multimodal files (audio, images, PDFs) and converts
them into structured JSON data matching the Senpai `sales_activities` schema.

It uses OpenAI's Whisper for audio transcription and GPT-4o for Vision/OCR.
It relies on the `OPENAI_API_KEY` environment variable for multimodal features.
The structuring step uses the local `llm/client.py` configuration.

Usage:
    python -m senpai.ingestion.multimodal --audio path/to/voice_memo.m4a
    python -m senpai.ingestion.multimodal --image path/to/business_card.jpg
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

# We use the local client for data structuring, and a separate standard OpenAI
# client for multimodal features (Whisper/Vision) since the local `exp3` model
# is text-only.
from senpai.llm.client import simple_complete

# Initialize the multimodal client (requires OPENAI_API_KEY)
# If no key is present, we'll gracefully fall back to mock returns so the
# pipeline doesn't crash during offline testing.
multimodal_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy"))


# ---------------------------------------------------------------------------
# Schema Definitions
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
        description="Titles, roles, and names of contacts extracted (e.g. '情報システム部 部長 鈴木')."
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
# Core Pipeline Functions
# ---------------------------------------------------------------------------
def transcribe_audio(file_path: str) -> str:
    """Uses Whisper to transcribe an audio file into Japanese text."""
    print(f"🎙️ [Audio] Transcribing {file_path} via Whisper API...")
    if os.environ.get("OPENAI_API_KEY") is None:
        print("⚠️ No OPENAI_API_KEY found. Returning mock transcription.")
        return "えー、今日アクメ商事の鈴木部長と面談しました。モバイル端末導入によるテレワークのセキュリティ強化が課題とのこと。予算次第で来月検討したいそうです。"

    try:
        with open(file_path, "rb") as audio_file:
            transcript = multimodal_client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                language="ja" # optimize for Japanese B2B sales
            )
        return transcript.text
    except Exception as e:
        print(f"❌ Audio transcription failed: {e}")
        return ""


def extract_text_from_image(file_path: str) -> str:
    """Uses Vision (GPT-4o) to extract text/context from an image."""
    print(f"📸 [Vision] Extracting text from {file_path} via Vision API...")
    if os.environ.get("OPENAI_API_KEY") is None:
        print("⚠️ No OPENAI_API_KEY found. Returning mock OCR data.")
        return "名刺抽出: アクメ商事株式会社 情報システム部 部長 鈴木一郎\nメモ: テレワーク、セキュリティ強化"

    try:
        with open(file_path, "rb") as image_file:
            b64 = base64.b64encode(image_file.read()).decode('utf-8')
        
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "image/jpeg"
        
        prompt = (
            "This is an image related to a B2B sales activity (e.g., a business card, "
            "a whiteboard, or a physical document). Extract all text exactly as written. "
            "If it's a business card, clearly list the Company, Department, Title, and Name. "
            "Output in Japanese."
        )

        response = multimodal_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}
                ]}
            ],
            max_tokens=500
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        print(f"❌ Vision extraction failed: {e}")
        return ""


def extract_structured_activity(raw_text: str) -> dict:
    """Uses the local model to structure the raw text into the strict schema."""
    print("🧠 [Extraction] Structuring raw text into Activity Schema...")
    system_prompt = (
        "You are a sales operations assistant. Extract structured sales activity data "
        "from the following raw text (which may be a transcribed voice note or OCR output). "
        "Output strictly in JSON format matching the requested schema. "
        "Do not invent information. If a field is not mentioned, leave it empty. "
        "IMPORTANT: For 'activity_type', you MUST choose exactly one of the allowed literal values. "
        "If you are unsure, default to '002_Daily Report'. NEVER output an empty string for activity_type."
    )
    
    schema_json = json.dumps(ActivityExtraction.model_json_schema(), ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Extract JSON from this raw text:\n\n{raw_text}\n\nOutput ONLY a JSON object that satisfies this schema:\n{schema_json}"}
    ]
    
    try:
        # Use local exp3/qwen model defined in Senpai config
        raw_response = simple_complete(messages, temperature=0.1, no_think=True)
        
        # Clean markdown code blocks if the model wrapped the JSON
        json_str = raw_response
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
            
        data = json.loads(json_str.strip())
        validated = ActivityExtraction(**data)
        return validated.model_dump()
    except Exception as e:
        print(f"⚠️ Extraction failed: {e}")
        # Fallback dictionary if parsing fails
        return {"activity_type": "002_Daily Report", "daily_report": raw_text}


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Standalone Multimodal Ingestion Pipeline")
    parser.add_argument("--audio", type=str, help="Path to an audio file (mp3, wav, m4a)")
    parser.add_argument("--image", type=str, help="Path to an image file (jpg, png)")
    parser.add_argument("--text", type=str, help="Raw text string to process directly")
    
    args = parser.parse_args()
    
    if not any([args.audio, args.image, args.text]):
        parser.print_help()
        print("\n❌ Error: Please provide at least one input source (--audio, --image, or --text).")
        return

    raw_content = []

    # 1. Process Modalities
    if args.audio:
        if os.path.exists(args.audio) or not os.environ.get("OPENAI_API_KEY"):
            transcription = transcribe_audio(args.audio)
            if transcription:
                raw_content.append(f"[音声文字起こし]: {transcription}")
        else:
            print(f"❌ File not found: {args.audio}")

    if args.image:
        if os.path.exists(args.image) or not os.environ.get("OPENAI_API_KEY"):
            ocr_text = extract_text_from_image(args.image)
            if ocr_text:
                raw_content.append(f"[画像OCR抽出]: {ocr_text}")
        else:
            print(f"❌ File not found: {args.image}")

    if args.text:
        raw_content.append(f"[テキスト入力]: {args.text}")

    # Combine all extracted context
    combined_raw_text = "\n\n".join(raw_content)
    
    if not combined_raw_text:
        print("❌ No valid content extracted. Exiting.")
        return

    print("\n--- 📄 Raw Extracted Content ---")
    print(combined_raw_text)
    print("--------------------------------\n")

    # 2. Structure the Data
    structured_data = extract_structured_activity(combined_raw_text)
    
    # 3. Output the final JSON
    print("✅ --- 🚀 Final Structured Output (Ready for DB) ---")
    print(json.dumps(structured_data, ensure_ascii=False, indent=2))
    print("---------------------------------------------------\n")

if __name__ == "__main__":
    main()
