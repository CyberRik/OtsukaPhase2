# Solution Advisor Test Prompts

## The Ambiguous Needs Prompt
We have introduced a core prompt to test the deterministic product recommendation capability ("Solution Advisor") within the Senpai Assistant.

### The Prompt
> お客様のC01について、最近ネットが遅くて業務に支障が出ていると相談を受けました。また、PCもWindows 8時代のもので古いです。予算にはシビアです。どのような提案をすべきですか？

### Purpose
This prompt specifically tests whether the system can correctly interpret ambiguous customer complaints and environment characteristics to retrieve concrete Otsuka product recommendations, rather than just returning general advice.

- **"ネットが遅くて業務に支障が出ている" (Slow internet bottleneck):** Should trigger network improvement solutions (e.g., Wireless Access Points or upgraded routers).
- **"PCもWindows 8時代のもので古い" (Legacy Windows 8 PCs):** Triggers the End-of-Life (EOL) environment rules.
- **"予算にはシビア" (Tight budget constraint):** Tests the system's ability to recommend phased or cost-effective migration plans.
- **"どのような提案をすべきですか？" (What should I propose?):** This question specifically invokes the `advise_solutions` tool.

### Expected System Behavior
1. The assistant's `JUNIOR` or `MANAGER` role logic intercepts the intent "What should I propose?" and executes the `advise_solutions` tool.
2. The deterministic engine evaluates customer C01's environment against expansion and upgrade triggers in `senpai/account/expansion.py`.
3. The engine fetches valid products from the mock catalog database (e.g., `WAP6 Wireless Access Point`).
4. The LLM narrative layer packages these items with reasonable business rationale and deployment considerations.
5. The assistant returns a highly grounded, artifact-based list of specific Otsuka solutions without hallucinating generic products.

### Usage
This prompt is saved in `prompt.txt` at the root of the project to allow for quick regression testing of the Recommendation Engine and the RAG agent's tool-dispatch logic.
