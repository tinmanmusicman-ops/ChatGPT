#!/usr/bin/env python3
"""
Launch the top-level config editor from the release tracker assets folder.
Running this file ensures the editor’s current directory is this bot-assets folder so the
project-specific config.json opens automatically.
"""

from pathlib import Path
import subprocess
import sys


def main() -> None:
    assets_dir = Path(__file__).resolve().parent
    config_path = assets_dir / "config.json"
    workspace_root = Path(__file__).resolve().parents[2]
    editor_path = workspace_root / "Indeed" / "config_editor.py"
    if not editor_path.exists():
        raise FileNotFoundError(f"Cannot find config_editor.py at {editor_path}")
    cmd = [sys.executable, str(editor_path)]
    if config_path.exists():
        cmd += ["--config", str(config_path)]
    subprocess.run(cmd, cwd=str(assets_dir))


if __name__ == "__main__":
    main()
