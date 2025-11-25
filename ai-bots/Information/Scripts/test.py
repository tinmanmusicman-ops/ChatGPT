from __future__ import annotations

import io
from pathlib import Path

import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


BASE_DIR = Path(__file__).resolve().parents[2]
CLIENT_SECRETS = BASE_DIR / "shared" / "tokens.json"
TOKENS_PATH = BASE_DIR / "shared" / "oauth_tokens.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TARGET_FOLDER_ID = "1LXcWHxSiw6A7nIRyIiWf7L2b-fCXeRYk"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def ensure_credentials() -> Credentials:
    creds = None
    if TOKENS_PATH.exists():
        creds = Credentials.from_authorized_user_file(TOKENS_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired OAuth token")
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS.exists():
                raise FileNotFoundError(f"Missing OAuth client secrets at {CLIENT_SECRETS}")
            logger.info("Launching OAuth consent flow")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKENS_PATH.write_text(creds.to_json(), encoding="utf-8")
        logger.info("Saved refreshed OAuth credentials")
    return creds


def upload_sample_report(drive, folder_id: str) -> None:
    content = "Sample report written via OAuth."
    media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype="text/html")
    metadata = {"name": "oauth-test-upload.html", "parents": [folder_id]}
    created = drive.files().create(body=metadata, media_body=media, fields="id, webViewLink").execute()
    logger.info("Uploaded sample report to folder %s (file id %s)", folder_id, created["id"])
    print(f"Uploaded: {created['webViewLink']} (id={created['id']})")


def list_all_drive_files(drive) -> None:
    token = None
    print("\nFull Drive listing:")
    logger.info("Listing drive items page-by-page")
    while True:
        response = (
            drive.files()
            .list(
                pageSize=100,
                fields="nextPageToken, files(id, name, mimeType, owners)",
                pageToken=token,
            )
            .execute()
        )
        files = response.get("files", [])
        if not files and token is None:
            print("  (no entries)")
            return
        for entry in files:
            owner = entry.get("owners", [{}])[0].get("emailAddress", "unknown")
            logger.info("Drive entry: %s (%s) owner %s id=%s", entry["name"], entry["mimeType"], owner, entry["id"])
            print(f"- {entry['name']} ({entry['mimeType']}) owner {owner} [{entry['id']}]")
        token = response.get("nextPageToken")
        if not token:
            break


def main() -> None:
    creds = ensure_credentials()
    drive = build("drive", "v3", credentials=creds)
    print("Drive files (page 1):")
    logger.info("Requesting first Drive page")
    response = (
        drive.files()
        .list(pageSize=5, fields="nextPageToken, files(id, name, mimeType)")
        .execute()
    )
    for entry in response.get("files", []):
        print(f"- {entry['name']} ({entry['mimeType']} / {entry['id']})")
    upload_sample_report(drive, TARGET_FOLDER_ID)
    list_all_drive_files(drive)


if __name__ == "__main__":
    main()
