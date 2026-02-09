from pathlib import Path
import sys

sys.stdout.reconfigure(encoding="utf-8")

source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("CORES.html")
start = int(sys.argv[2]) if len(sys.argv) > 2 else 430
end = int(sys.argv[3]) if len(sys.argv) > 3 else 490

lines = source.read_text(encoding="utf-8").splitlines()
for i in range(start, min(end, len(lines))):
    print(f"{i+1:03}: {lines[i]}")
