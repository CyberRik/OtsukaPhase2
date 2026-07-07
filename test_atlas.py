import urllib.request
import json
import time

url = 'http://127.0.0.1:8888/v1/chat/completions'
long_text = 'apple banana ' * 60000

data = json.dumps({
    'model': 'atlas-35b',
    'messages': [{'role': 'user', 'content': 'Can you read this long text? Just reply with exactly YES. ' + long_text}],
    'max_tokens': 10
}).encode('utf-8')

req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

print("Sending 120k word prompt (~150k tokens)...")
start = time.time()
try:
    with urllib.request.urlopen(req) as response:
        print(response.read().decode())
except Exception as e:
    print(f"Error: {e}")
print(f"Time taken: {time.time() - start:.2f} seconds")
