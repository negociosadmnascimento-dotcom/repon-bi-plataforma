import json, re

transcript_path = r'C:\Users\negoc\.gemini\antigravity\brain\23719646-44f5-48d3-b5b8-005afbb1b243\.system_generated\logs\transcript.jsonl'
with open(transcript_path, encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Find all postgresql URLs in the transcript
urls = re.findall(r'postgresql://[^\s\'"\\]+', content)
seen = set()
for url in urls:
    # Remove escape chars
    clean = url.replace('\\n', '').replace("\\'", "'").replace('\\"', '"')
    if clean not in seen and len(clean) > 30:
        seen.add(clean)
        print(clean[:200])
        print()
