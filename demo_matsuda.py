import os
import sys
from senpai.matsuda import build_matsuda_context

def main():
    print("Building MatsudaContext...")
    ctx = build_matsuda_context()
    
    report_path = os.path.join(os.path.dirname(__file__), "report.md")
    print(f"\nWriting inspectable report to {report_path}...")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(ctx.to_markdown())
        
    questions = [
        "Tell me about Matsuda",
        "What are the biggest risks?",
        "Who is the decision maker?",
        "When was the last meeting?",
        "What products are they interested in?",
        "What should I do next?",
        "Tell me about their IT environment",
        "How is the health of the deals?",
        "Who owns these deals?",
        "What is the total pipeline value?"
    ]
    
    print("\n--- Running 10 Q&A against Context ---")
    for q in questions:
        print(f"\nQ: {q}")
        print(f"A: {ctx.answer(q)}")

if __name__ == "__main__":
    main()
