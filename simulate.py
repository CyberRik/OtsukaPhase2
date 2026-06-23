import sys
import time
from datetime import date
import os

# Ensure the root is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from senpai.coach.review import review_note, narrate_review

note = "本日はご挨拶のみ。次回は日程未定ですが、検討しますとのことでした。"

print("Starting Review Coach simulation (GGUF via vLLM)...")
start_time = time.time()

# 1. Deterministic coaching evaluation
review = review_note(note)
eval_time = time.time()
print(f"Deterministic logic done in: {eval_time - start_time:.4f} seconds")

# 2. Narration via LLM (this tests the latency)
print("Sending to LLM...")
narration = narrate_review(review, use_llm=True)

end_time = time.time()
print(f"\n--- TIMING ---")
print(f"LLM Generation Time: {end_time - eval_time:.2f} seconds")
print(f"Total Turnaround Time: {end_time - start_time:.2f} seconds")

print(f"\n--- NARRATION OUTPUT ---")
print(narration)
