#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve()
    web_dir = here.parent.parent / "Web"
    md_path = web_dir / "dashboard_operator_manual.md"
    txt_path = web_dir / "dashboard_operator_manual.txt"
    if not md_path.exists():
        raise SystemExit(f"Missing {md_path}; run build_dashboard_operator_manual_md.py first.")
    txt_path.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(txt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

