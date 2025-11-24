#!/usr/bin/env python3
"""
Launch the shared config editor from this bot-assets folder.
Setting cwd to the assets directory makes the editor open its local config.json directly.
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
