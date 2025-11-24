from pathlib import Path
import re
text = Path("seam_thermostat_temp.py").read_text()
keys = set(re.findall(r'cfg\["([^\"]+)"\]', text))
print(sorted(keys))
