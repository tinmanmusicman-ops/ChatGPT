from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import logging
import mimetypes
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload


LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_install_root() -> Path:
    """Find the install root from shared/Global.json (InstallDir) or default upwards."""
    global_json = SCRIPT_DIR.parents[2] / "shared" / "Global.json"
    if global_json.exists():
        try:
            payload = json.loads(global_json.read_text(encoding="utf-8"))
            install_dir = payload.get("InstallDir")
            if install_dir:
                logger.info("InstallDir from Global.json: %s", install_dir)
                return Path(install_dir)
        except Exception as exc:
            logger.warning("Failed to read %s (%s); using default root", global_json, exc)
    return SCRIPT_DIR.parents[2]


INSTALL_ROOT = _load_install_root()
AI_BOTS_ROOT = INSTALL_ROOT / "ai-bots"
SHARED_DIR = AI_BOTS_ROOT / "shared"
TOKEN_PATH = SHARED_DIR / "Tokens.json"
TEMP_DIR = AI_BOTS_ROOT / "Temp"


def _load_credentials() -> Credentials:
    """Load OAuth user credentials from Tokens.json (already contains client id/secret)."""
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"Missing OAuth token file at {TOKEN_PATH}")
    token_info = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(token_info, scopes=SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            logger.info("Refreshing access token")
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise FileNotFoundError(
                f"Token at {TOKEN_PATH} is invalid/expired and has no refresh token"
            )
    return creds


def get_drive_service():
    """Return an authenticated Drive v3 client."""
    creds = _load_credentials()
    logger.info("Building Drive service client")
    return build("drive", "v3", credentials=creds)


def get_or_create_drive_folder(service, folder_name: str) -> str:
    """Find a Drive folder by name or create it."""
    escaped = folder_name.replace("'", "\\'")
    query = (
        f"name = '{escaped}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    resp = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id,name)", pageSize=5)
        .execute()
    )
    files = resp.get("files", [])
    if files:
        folder_id = files[0]["id"]
        logger.info("Found existing folder %s (%s)", folder_name, folder_id)
        return folder_id

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    created = service.files().create(body=metadata, fields="id,name").execute()
    folder_id = created["id"]
    logger.info("Created folder %s (%s)", folder_name, folder_id)
    return folder_id


def _next_version_name(desired: str, existing_names: List[str]) -> str:
    """If desired exists, append _vN (starting at 2) before extension."""
    if desired not in existing_names:
        return desired
    stem = Path(desired).stem
    suffix = Path(desired).suffix
    counter = 2
    candidate = f"{stem}_v{counter}{suffix}"
    while candidate in existing_names:
        counter += 1
        candidate = f"{stem}_v{counter}{suffix}"
    return candidate


def upload_or_version_file(
    service,
    folder_id: str,
    filename: str,
    content: bytes,
    mime_type: str,
) -> Tuple[str, str]:
    """Upload content; if name exists, create a versioned copy."""
    # Gather existing file names in the folder (bounded for safety).
    resp = (
        service.files()
        .list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id,name)",
            pageSize=200,
        )
        .execute()
    )
    existing = resp.get("files", [])
    existing_names = [f["name"] for f in existing]
    target_name = _next_version_name(filename, existing_names)
    media = MediaInMemoryUpload(content, mimetype=mime_type, resumable=False)
    body = {"name": target_name, "parents": [folder_id]}
    created = service.files().create(body=body, media_body=media, fields="id,name").execute()
    file_id = created["id"]
    logger.info("Uploaded %s as %s (file id %s)", filename, target_name, file_id)
    return file_id, target_name


def push_content_to_drive(
    folder_name: str,
    filename: str,
    content: bytes,
    mime_type: Optional[str] = None,
) -> str:
    """High-level helper to push arbitrary bytes to Drive with versioned naming."""
    service = get_drive_service()
    folder_id = get_or_create_drive_folder(service, folder_name)
    mime = mime_type or "application/octet-stream"
    file_id, target_name = upload_or_version_file(
        service, folder_id, filename, content, mime
    )
    logger.info(
        "Drive link: https://drive.google.com/file/d/%s/view (stored as %s)",
        file_id,
        target_name,
    )
    return file_id


def _iter_local_files(directory: Path):
    for entry in sorted(directory.iterdir()):
        if entry.is_file():
            yield entry


if __name__ == "__main__":
    """Upload all files in ai-bots/Temp to Drive folder 'ChatGPT' (versioned), then delete them."""
    os.chdir(SCRIPT_DIR)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    files = list(_iter_local_files(TEMP_DIR))
    if not files:
        raise SystemExit(f"No files found in {TEMP_DIR}; drop something there to upload.")

    service = get_drive_service()
    folder_id = get_or_create_drive_folder(service, "ChatGPT")

    for path in files:
        mime_type, _enc = mimetypes.guess_type(path.name)
        mime_type = mime_type or "application/octet-stream"
        content = path.read_bytes()
        _, target_name = upload_or_version_file(
            service, folder_id, path.name, content, mime_type
        )
        logger.info("Uploaded %s as %s; deleting local copy", path.name, target_name)
        try:
            path.unlink()
        except Exception as exc:
            logger.warning("Unable to delete %s (%s)", path, exc)

