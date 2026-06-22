from senpai.data import store

customers = store.all_customers()
print("Total customers:", len(customers))
for c in customers[:5]:
    print(" ", c.get("customer_id"), repr(c.get("name", "")[:30]))

print("\nAlias index keys (first 10):")
idx = store._alias_index()
for k in list(idx.keys())[:10]:
    print(" ", repr(k), "->", idx[k])

# Try direct match
m = store.match_customer_in_text("the customer wants a discount")
print("\nMatch (English):", m)

m2 = store.match_customer_in_text("acme")
print("Match (acme):", m2)

# Check aliases file
import json
from pathlib import Path
alias_path = Path("senpai/data/seed/customer_aliases.json")
if alias_path.exists():
    aliases = json.loads(alias_path.read_text(encoding="utf-8"))
    for k, v in list(aliases.items())[:5]:
        print("alias:", repr(k), "->", v)
else:
    print("No customer_aliases.json found")

# Fuzzy test
c4, score = store.fuzzy_match_customer_in_text("acme commercial trading")
print("\nFuzzy (acme commercial trading):", c4, round(score, 2))
