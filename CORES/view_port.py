from pathlib import Path
import sys

sys.stdout.reconfigure(encoding="utf-8")

lines = Path("Job.html").read_text(encoding="utf-8").splitlines()
for i in range(430, 490):
    print(f"{i+1:03}: {lines[i]}")
