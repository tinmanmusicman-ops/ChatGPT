from __future__ import annotations

import json
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

def locate_global_config() -> Path:
    candidate = Path(__file__).resolve()
    while True:
        shared = candidate / "shared" / "Global.json"
        if shared.exists():
            return shared
        alt = candidate / "ai-bots" / "shared" / "Global.json"
        if alt.exists():
            return alt
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    raise FileNotFoundError("shared/Global.json not found")

CONFIG_PATH = locate_global_config()


def main() -> None:
    """Instantiate the service account and list the first five Drive objects."""
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        data,
        scopes=["https://www.googleapis.com/auth/drive.metadata.readonly"],
    )
    drive = build("drive", "v3", credentials=creds)
    response = (
        drive.files()
        .list(pageSize=5, fields="nextPageToken, files(id, name, mimeType)")
        .execute()
    )
    files = response.get("files", [])
    if not files:
        print("No Drive files found with this service account.")
        return

    print("Drive files accessible via the service account:")
    for entry in files:
        print(f"- {entry['name']} ({entry['mimeType']} / {entry['id']})")


if __name__ == "__main__":
    main()
