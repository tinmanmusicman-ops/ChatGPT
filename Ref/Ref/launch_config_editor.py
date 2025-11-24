#!/usr/bin/env python3
"""
Helper that enumerates every ai-bots/*/bot-assets/config.json and lets you choose
which project to edit from a single launcher. Once you make a selection the shared
config_editor.py is invoked with the selected config path, ensuring the GUI opens
with that file.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


def discovery() -> List[Tuple[str, Path]]:
    base = Path(__file__).resolve().parent
    results = []
    for child in sorted(base.iterdir()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        assets = child / "bot-assets" / "config.json"
        if assets.exists():
            results.append((child.name, assets))
    return results


def prompt(options: List[Tuple[str, Path]]) -> Path:
    print("Available configs:")
    for idx, (label, path) in enumerate(options, start=1):
        print(f"  {idx}. {label} ({path})")
    choice = 1
    if len(options) > 1:
        while True:
            raw = input(f"Pick a config [1-{len(options)}] (default=1): ").strip()
            if not raw:
                break
            if raw.isdigit():
                val = int(raw)
                if 1 <= val <= len(options):
                    choice = val
                    break
            print("Invalid selection.")
    return options[choice - 1][1]


def main() -> None:
    options = discovery()
    if not options:
        raise SystemExit("No `bot-assets/config.json` files were found under ai-bots/")
    config_path = prompt(options)
    workspace = Path(__file__).resolve().parents[1]
    editor = workspace / "Indeed" / "config_editor.py"
    if not editor.exists():
        raise FileNotFoundError(f"Cannot find shared editor at {editor}")
    subprocess.run([sys.executable, str(editor), "--config", str(config_path)], cwd=str(config_path.parent))


if __name__ == "__main__":
    main()
