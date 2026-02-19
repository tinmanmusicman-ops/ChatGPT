from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


class HSSTLogger:
    def __init__(self, log_file: str = "") -> None:
        self.log_file = log_file
        if self.log_file:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

    def event(self, event: str, **fields: Any) -> None:
        record = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=True)
        print(line)
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")

