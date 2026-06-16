import re
content = open('app.py', 'r', encoding='utf-8').read()
# Find all route decorators
routes = re.findall(r"@app\.route\('([^']+)'", content)
print("=== ALL ROUTES ===")
for r in sorted(set(routes)):
    print(f"  {r}")
