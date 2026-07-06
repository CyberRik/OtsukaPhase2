import os

def get_codebase():
    content = ""
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', 'env')]
            
        for file in files:
            if file.endswith(('.ts', '.tsx', '.py', '.md')) and not file.startswith('massive'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content += f"// File: {path}\n"
                        content += f.read() + "\n\n"
                except:
                    pass
    return content

codebase = get_codebase()

print(f"Base codebase size: {len(codebase)} characters")

iterations = 5
prompt = "You are a senior architect. I am providing you with multiple iterations of our entire codebase to analyze its evolution over time and suggest deep architectural improvements.\n\n"

for i in range(iterations):
    prompt += f"==================== ITERATION {i+1} ====================\n\n"
    # To avoid exact duplication (which compression or prefix caching might collapse entirely),
    # let's inject some dummy changes.
    modified_codebase = codebase.replace('def ', f'def iteration_{i+1}_').replace('function ', f'function iteration_{i+1}_')
    prompt += modified_codebase + "\n\n"
    
    # Check if we have enough size to hit ~1MB
    if len(prompt) > 1000000:
        break

prompt += """
Based on the massive codebase history provided above:
1. Identify memory leaks or React re-rendering bottlenecks in the `web` component iterations.
2. Outline a scaling strategy for the `senpai` backend assuming we 100x the load.
3. Suggest 3 specific optimizations for the Atlas model integration in our python server.
4. Give me a detailed timeline for this refactoring plan.
"""

with open('massive_prompt.txt', 'w', encoding='utf-8') as f:
    f.write(prompt)

print(f"Massive prompt generated: {len(prompt)} characters (~{len(prompt)//4} tokens). Saved to massive_prompt.txt.")
