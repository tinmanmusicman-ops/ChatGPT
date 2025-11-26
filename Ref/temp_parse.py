from pathlib import Path
import re

text = Path("C:/ChatGPT/ai-bots/Jobs/scripts/Indeed.py").read_text(encoding="utf-8", errors="ignore")
pattern = re.compile(r'cfg\["([^"]+)"\]')
keys = set(pattern.findall(text))
print("\n".join(sorted(keys)))
