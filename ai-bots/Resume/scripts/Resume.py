#!/usr/bin/env python3
"""
Resume Engine
==============

Reads a job description from the clipboard, loads the base resume data, calls an
AI model, and writes the tailored resume (TXT and PDF) plus the cover letter.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import gspread
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Frame, ListFlowable, ListItem, PageTemplate, Paragraph, SimpleDocTemplate, Spacer

try:
    from openai import OpenAI
except ImportError as exc:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]
    OPENAI_IMPORT_ERROR = exc  # type: ignore[name-defined]
else:
    OPENAI_IMPORT_ERROR = None  # type: ignore[name-defined]

HYPHEN = "-"
SOFT_BLACK = colors.HexColor("#1A1A1A")
SOFT_WHITE = colors.HexColor("#F2F2F2")
client: Optional[OpenAI] = None

ROOT_DIR = Path(__file__).resolve().parent.parent
AI_BOTS_ROOT = ROOT_DIR.parent
SHARED_CONFIG_PATH = AI_BOTS_ROOT / "shared" / "Global.json"
BOT_ASSETS_DIR = ROOT_DIR / "bot-assets"
CONFIG_PATH = BOT_ASSETS_DIR / "config.json"
RESUME_TEXT_OUTPUT_PATH: Optional[Path] = None
PDF_OUTPUT_PATH: Optional[Path] = None
COVER_LETTER_PDF_PATH: Optional[Path] = None
JOB_DESCRIPTION_PDF_PATH: Optional[Path] = None
JOB_ID: Optional[str] = None
SERVICE_ACCOUNT_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
)
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_PATH = AI_BOTS_ROOT / "shared" / "Tokens.json"
TARGETED_RESUMES_FOLDER_NAME = "Targeted Resumes"
SERVICE_ACCOUNT_REQUIRED_KEYS = (
    "type",
    "project_id",
    "private_key_id",
    "private_key",
    "client_email",
    "client_id",
    "auth_uri",
    "token_uri",
    "auth_provider_x509_cert_url",
    "client_x509_cert_url",
    "universe_domain",
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    config = load_json(path)
    if not isinstance(config, dict):
        raise ValueError("Config file must contain a JSON object at the top level.")
    return config


def configure_logger(config: Dict[str, Any]) -> logging.Logger:
    logging_enabled = bool(config.get("logging", False))
    debug_mode = bool(config.get("debug", False))
    level = logging.DEBUG if debug_mode else (logging.INFO if logging_enabled else logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logger = logging.getLogger("ResumeEngine")
    logger.setLevel(level)
    return logger


@dataclass
class SheetConfig:
    job_description_column: str
    company_column: str
    job_title_column: str
    resume_link_column: str
    cover_letter_link_column: str
    processed_timestamp_column: str


def _required_config_value(config: Dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not value:
        raise KeyError(f"Missing required config key: {key}")
    return str(value)


def load_sheet_config(config: Dict[str, Any]) -> SheetConfig:
    return SheetConfig(
        job_description_column=_required_config_value(config, "job_description_column"),
        company_column=_required_config_value(config, "company_column"),
        job_title_column=_required_config_value(config, "job_title_column"),
        resume_link_column=_required_config_value(config, "resume_link_column"),
        cover_letter_link_column=_required_config_value(config, "cover_letter_link_column"),
        processed_timestamp_column=_required_config_value(config, "processed_timestamp_column"),
    )


def load_service_account_credentials() -> service_account.Credentials:
    if not SHARED_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing shared credentials file: {SHARED_CONFIG_PATH}")
    payload = load_json(SHARED_CONFIG_PATH)
    info = {key: payload.get(key) for key in SERVICE_ACCOUNT_REQUIRED_KEYS}
    missing = [key for key, value in info.items() if not value]
    if missing:
        raise RuntimeError(f"Shared credentials missing fields: {', '.join(missing)}")
    return service_account.Credentials.from_service_account_info(info, scopes=SERVICE_ACCOUNT_SCOPES)


def _get_env_int(name: str) -> Optional[int]:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer") from exc


def _get_env_str(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if not value:
        return None
    stripped = value.strip()
    return stripped or None


def _sanitize_drive_segment(value: str, fallback: str) -> str:
    normalized = value.strip()
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^\w\-]", "", normalized)
    return normalized or fallback


def _load_drive_credentials(logger: logging.Logger) -> Credentials:
    """Load user OAuth credentials from shared Tokens.json for Drive uploads."""
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"Missing OAuth token file at {TOKEN_PATH}")
    token_info = load_json(TOKEN_PATH)
    creds = Credentials.from_authorized_user_info(token_info, scopes=DRIVE_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            logger.info("Refreshing Drive access token")
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                f"Drive OAuth token at {TOKEN_PATH} is invalid/expired and has no refresh token"
            )
    return creds


def get_drive_upload_service(logger: logging.Logger):
    creds = _load_drive_credentials(logger)
    logger.debug("Building Drive upload service client")
    return build("drive", "v3", credentials=creds)


@dataclass
class WorksheetContext:
    worksheet: gspread.Worksheet
    title: str
    row_index: int


def resolve_marker_context(
    credentials: service_account.Credentials,
    spreadsheet_id: str,
    logger: logging.Logger,
    *,
    marker_col: int = 2,
    marker_value: str = "X",
) -> WorksheetContext:
    client = gspread.authorize(credentials)
    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
    except SpreadsheetNotFound as exc:
        raise RuntimeError(f"Spreadsheet {spreadsheet_id} not available") from exc

    matches: list[WorksheetContext] = []
    for worksheet in spreadsheet.worksheets():
        if worksheet.title.startswith("_"):
            logger.debug("Skipping system worksheet '%s'", worksheet.title)
            continue
        try:
            row_idx = _find_job_row_by_marker(
                worksheet, marker_col=marker_col, marker_value=marker_value
            )
        except Exception as exc:
            logger.debug(
                "Skipping worksheet '%s' due to marker scan error: %s",
                worksheet.title,
                exc,
            )
            continue
        if row_idx is not None:
            matches.append(
                WorksheetContext(
                    worksheet=worksheet,
                    title=worksheet.title,
                    row_index=row_idx,
                )
            )

    if not matches:
        titles = [ws.title for ws in spreadsheet.worksheets()]
        raise RuntimeError(
            "No worksheet context found. Mark the target row with 'X' in column B. "
            f"Available worksheets: {', '.join(titles)}"
        )

    if len(matches) > 1:
        logger.warning(
            "Multiple worksheets contain marker '%s' in column %s; using first match in '%s'. Matches: %s",
            marker_value,
            marker_col,
            matches[0].title,
            ", ".join(m.title for m in matches),
        )
    return matches[0]


def _find_or_add_header(
    worksheet: gspread.Worksheet,
    headers: list[str],
    column_name: str,
    *,
    required: bool,
    logger: logging.Logger,
) -> int:
    normalized = column_name.strip().lower()
    for idx, header_value in enumerate(headers, start=1):
        if header_value.strip().lower() == normalized:
            return idx
    if required:
        raise RuntimeError(f"Missing required column '{column_name}' in worksheet")
    headers.append(column_name)
    col_idx = len(headers)
    worksheet.update_cell(1, col_idx, column_name)
    logger.debug("Added header '%s' in column %s", column_name, col_idx)
    return col_idx


def _collect_header_indices(
    worksheet: gspread.Worksheet,
    sheet_config: SheetConfig,
    logger: logging.Logger,
) -> dict[str, int]:
    headers = [value.strip() for value in worksheet.row_values(1)]
    mapping: dict[str, int] = {}
    mapping[sheet_config.job_description_column] = _find_or_add_header(
        worksheet, headers, sheet_config.job_description_column, required=True, logger=logger
    )
    mapping[sheet_config.company_column] = _find_or_add_header(
        worksheet, headers, sheet_config.company_column, required=True, logger=logger
    )
    mapping[sheet_config.job_title_column] = _find_or_add_header(
        worksheet, headers, sheet_config.job_title_column, required=True, logger=logger
    )
    mapping[sheet_config.resume_link_column] = _find_or_add_header(
        worksheet, headers, sheet_config.resume_link_column, required=False, logger=logger
    )
    mapping[sheet_config.cover_letter_link_column] = _find_or_add_header(
        worksheet, headers, sheet_config.cover_letter_link_column, required=False, logger=logger
    )
    mapping[sheet_config.processed_timestamp_column] = _find_or_add_header(
        worksheet, headers, sheet_config.processed_timestamp_column, required=False, logger=logger
    )
    return mapping


def _find_job_row_by_marker(
    worksheet: gspread.Worksheet, marker_col: int = 2, marker_value: str = "X"
) -> Optional[int]:
    try:
        values = worksheet.col_values(marker_col)
    except Exception:
        return None
    matches = [
        idx
        for idx, cell in enumerate(values, start=1)
        if idx != 1 and cell.strip().upper() == marker_value.upper()
    ]
    if not matches:
        return None
    if len(matches) > 1:
        return matches[0]
    return matches[0]


def _safe_row_value(row_values: list[str], col_idx: int) -> str:
    if col_idx - 1 < len(row_values):
        return row_values[col_idx - 1].strip()
    return ""


def _get_or_create_drive_folder(
    service, folder_name: str, parent_id: Optional[str] = None
) -> str:
    escaped = folder_name.replace("'", "\\'")
    query_parts = [
        f"name = '{escaped}'",
        "mimeType = 'application/vnd.google-apps.folder'",
        "trashed = false",
    ]
    if parent_id:
        query_parts.append(f"'{parent_id}' in parents")
    resp = (
        service.files()
        .list(q=" and ".join(query_parts), spaces="drive", fields="files(id,name)", pageSize=5)
        .execute()
    )
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    created = service.files().create(body=metadata, fields="id").execute()
    return created["id"]


def _upload_file_to_drive(
    service,
    folder_id: str,
    content_path: Path,
    target_name: str,
) -> str:
    media = MediaFileUpload(str(content_path), mimetype="application/pdf")
    body = {"name": target_name, "parents": [folder_id]}
    created = service.files().create(body=body, media_body=media, fields="id").execute()
    return created["id"]


def upload_pdfs_and_update_sheet(
    worksheet: gspread.Worksheet,
    headers: dict[str, int],
    row_number: int,
    resume_pdf: Path,
    cover_letter_pdf: Path,
    job_description_pdf: Path,
    sheet_config: SheetConfig,
    logger: logging.Logger,
) -> None:
    row_values = worksheet.row_values(row_number)
    company_value = _get_env_str("RESUME_COMPANY") or _safe_row_value(
        row_values, headers[sheet_config.company_column]
    )
    job_title_value = _get_env_str("RESUME_JOB_TITLE") or _safe_row_value(
        row_values, headers[sheet_config.job_title_column]
    )
    sanitized_company = _sanitize_drive_segment(company_value, "Company")
    sanitized_job_title = _sanitize_drive_segment(job_title_value, "JobTitle")
    date_prefix = datetime.now(timezone.utc).date().isoformat()
    folder_name = f"{date_prefix}_{sanitized_company}_{sanitized_job_title}_ROW{row_number}"
    drive_service = get_drive_upload_service(logger)
    root_folder_id = _get_or_create_drive_folder(drive_service, TARGETED_RESUMES_FOLDER_NAME)
    run_folder_id = _get_or_create_drive_folder(
        drive_service, folder_name, parent_id=root_folder_id
    )
    base_name = f"{sanitized_company}_{sanitized_job_title}_ROW{row_number}"
    resume_target_name = f"{base_name}_Resume.pdf"
    cover_target_name = f"{base_name}_CoverLetter.pdf"
    jd_target_name = f"{base_name}_JobDescription.pdf"
    resume_file_id = _upload_file_to_drive(drive_service, run_folder_id, resume_pdf, resume_target_name)
    cover_file_id = _upload_file_to_drive(
        drive_service, run_folder_id, cover_letter_pdf, cover_target_name
    )
    jd_file_id = _upload_file_to_drive(
        drive_service, run_folder_id, job_description_pdf, jd_target_name
    )
    resume_link = f"https://drive.google.com/file/d/{resume_file_id}/view"
    cover_link = f"https://drive.google.com/file/d/{cover_file_id}/view"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    worksheet.update_cell(row_number, headers[sheet_config.resume_link_column], resume_link)
    worksheet.update_cell(row_number, headers[sheet_config.cover_letter_link_column], cover_link)
    worksheet.update_cell(row_number, headers[sheet_config.processed_timestamp_column], timestamp)
    logger.info(
        "Uploaded PDFs for row %s to Drive folder %s (resume=%s cover_letter=%s jd=%s) and recorded links in spreadsheet",
        row_number,
        folder_name,
        resume_file_id,
        cover_file_id,
        jd_file_id,
    )






def build_prompt(job_description: str, base_resume: Dict[str, Any]) -> str:
    base_json = json.dumps(base_resume, indent=2, ensure_ascii=False)
    prompt = (
        "Base resume JSON:\n"
        f"{base_json}\n\n"
        "Job description:\n"
        f"{job_description.strip()}\n\n"
        "Return a JSON object that contains exactly two keys: "
        "`resume` and `cover_letter`. Do not wrap the JSON in markdown or code fence. "
        "Each value should be a polished, fully formatted document adapted to the job."
    )
    return prompt


def _read_clipboard_with_pyperclip() -> Optional[str]:
    try:
        import pyperclip
    except ImportError:
        return None
    try:
        return pyperclip.paste()
    except Exception:
        return None


def _clipboard_command_options() -> list[list[str]]:
    system = platform.system()
    if system == "Windows":
        return [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]]
    if system == "Darwin":
        return [["/usr/bin/pbpaste"]]
    return [
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ]


def _run_clipboard_command(command: list[str]) -> Optional[str]:
    if not command:
        return None
    if shutil.which(command[0]) is None:
        return None
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout


def get_job_description_from_clipboard() -> str:
    text = _read_clipboard_with_pyperclip()
    if text:
        return text
    for command in _clipboard_command_options():
        output = _run_clipboard_command(command)
        if output:
            return output
    raise RuntimeError("Unable to read job description from the clipboard.")


def get_openai_client(logger: logging.Logger) -> OpenAI:
    global client
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK import failed.")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required.")
    client = OpenAI(api_key=api_key)
    logger.debug("OpenAI client initialized with provided API key.")
    return client


def generate_documents(
    base_resume: Dict[str, Any],
    job_description: str,
    config: Dict[str, Any],
    logger: logging.Logger,
) -> Dict[str, str]:
    openai_client = get_openai_client(logger)

    messages = [
        {
            "role": "system",
            "content": "You are an expert resume writer who adapts a base resume "
            "JSON payload into tailored resumes and cover letters based on job descriptions.",
        },
        {
            "role": "user",
            "content": build_prompt(job_description, base_resume),
        },
    ]

    model = str(config.get("model", "gpt-4.1"))
    temperature = float(config.get("temperature", 0.2))
    max_tokens = int(config.get("max_tokens", 8000))
    logger.debug(
        "Calling model %s with temperature=%s max_tokens=%s", model, temperature, max_tokens
    )

    response = openai_client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=messages,
    )

    content = response.choices[0].message.content
    logger.debug("Model response: %s", content[:500])
    return extract_json_payload(content)


def extract_json_payload(text: str) -> Dict[str, str]:
    trimmed = text.strip()
    if not trimmed:
        raise ValueError("Received an empty response from the AI model.")

    try:
        payload = json.loads(trimmed)
    except json.JSONDecodeError:
        start = trimmed.find("{")
        end = trimmed.rfind("}")
        if start == -1 or end == -1:
            raise
        payload = json.loads(trimmed[start : end + 1])

    if not isinstance(payload, dict):
        raise ValueError("AI response JSON must be an object.")

    resume_text = str(payload.get("resume", "")).strip()
    cover_letter_text = str(payload.get("cover_letter", "")).strip()
    if not resume_text or not cover_letter_text:
        raise ValueError("Both `resume` and `cover_letter` fields must be non-empty.")

    return {"resume": resume_text, "cover_letter": cover_letter_text}


def normalize_dashes(text: str) -> str:
    normalized = text.replace("--", HYPHEN)
    normalized = normalized.replace("—", HYPHEN)
    normalized = normalized.replace("–", HYPHEN)
    normalized = normalized.replace("ƒ?", HYPHEN)
    return normalized


HEADING_TITLES = {
    "SUMMARY": ["SUMMARY"],
    "Key Skills": ["Key Skills"],
    "Recent Achievements": ["Recent Achievements"],
    "Professional Experience": ["Professional Experience"],
    "EDUCATION": ["EDUCATION"],
    "Relevant Project Experience": ["Relevant Project Experience"],
    "Certifications": ["Certifications"],
    "References": ["References available upon request.", "References available upon request"],
}

ORDERED_SECTIONS = [
    "SUMMARY",
    "Key Skills",
    "Recent Achievements",
    "Professional Experience",
    "EDUCATION",
    "Certifications",
    "References",
]

BASE_RESUME_PATH = BOT_ASSETS_DIR / "base_resume.json"


def _heading_candidate(line: str) -> tuple[str, bool] | tuple[None, bool]:
    stripped = line.strip()
    if not stripped:
        return None, False
    candidate = stripped.rstrip(":")
    for canonical, options in HEADING_TITLES.items():
        for option in options:
            if candidate.lower() == option.lower():
                return canonical, canonical == "References"
    return None, False


def parse_resume_into_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in text.replace("\r", "").splitlines():
        line = raw_line.strip()
        if not line:
            current_section = None
            continue
        heading, is_reference = _heading_candidate(line)
        if heading is None:
            candidate = line.rstrip(":")
            if line.endswith(":") and candidate:
                heading = candidate
            elif line.isupper() and len(line) > 3:
                heading = candidate
        if heading:
            current_section = heading
            if is_reference:
                sections.setdefault("References", []).append("References available upon request.")
                current_section = None
            continue
        if current_section:
            sections.setdefault(current_section, []).append(line)
    return sections


def _flush_bullets(bullets: list[str], story: list, body_style: ParagraphStyle) -> None:
    if not bullets:
        return
    bullet_items = [
        ListItem(Paragraph(re.sub(r"^[-•]+\s*", "", line), body_style))
        for line in bullets
    ]
    story.append(
        ListFlowable(
            bullet_items,
            bulletType="bullet",
            leftIndent=0.25 * inch,
            bulletFontName="Helvetica",
            bulletFontSize=11,
            bulletColor=SOFT_WHITE,
        )
    )


def load_base_resume_data() -> Dict[str, Any]:
    if not BASE_RESUME_PATH.exists():
        return {}
    return load_json(BASE_RESUME_PATH)


def build_summary_lines(base_resume: Dict[str, Any]) -> list[str]:
    summary = base_resume.get("summary")
    return [summary] if summary else []


def build_skills_lines(base_resume: Dict[str, Any]) -> list[str]:
    return [f"- {skill}" for skill in base_resume.get("skills", [])]


def build_achievements_lines(base_resume: Dict[str, Any]) -> list[str]:
    return [f"- {item}" for item in base_resume.get("achievements_2024_2025", [])]


def build_experience_lines(base_resume: Dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for job in base_resume.get("experience", []):
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "")
        start = job.get("start", "")
        end = job.get("end", "")
        header = f"{title} {HYPHEN} {company}, {location} ({start} {HYPHEN} {end})"
        lines.append(header)
        for highlight in job.get("highlights", []):
            lines.append(f"- {highlight}")
    return lines


def build_education_lines(base_resume: Dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for entry in base_resume.get("education", []):
        degree = entry.get("degree", entry.get("program", ""))
        school = entry.get("school", entry.get("provider", ""))
        location = entry.get("location", "")
        date = entry.get("date", "")
        summary_line = f"{degree} {HYPHEN} {school}"
        if location:
            summary_line += f", {location}"
        if date:
            summary_line += f" ({date})"
        lines.append(summary_line)
    return lines


def build_certifications_lines(base_resume: Dict[str, Any]) -> list[str]:
    return [f"- {cert}" for cert in base_resume.get("certifications", [])]


def build_references_lines(base_resume: Dict[str, Any]) -> list[str]:
    references = base_resume.get("references")
    if references:
        return references if isinstance(references, list) else [references]
    return ["References available upon request."]
def _looks_like_structured_data_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped[0] in "{[":
        return True
    if "{" in stripped or "}" in stripped or "[" in stripped or "]" in stripped:
        return True
    return False


def extract_name(text: str, base_resume: Dict[str, Any]) -> str:
    fallback = base_resume.get("name")
    for raw_line in text.replace("\r", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading, _ = _heading_candidate(line)
        if heading:
            continue
        if _looks_like_structured_data_line(line):
            continue
        return line
    return fallback or "NAME"


def draw_gradient_bg(canvas, doc) -> None:
    canvas.saveState()
    page_width, page_height = letter
    shading = canvas.linearGradient(
        0,
        page_height,
        0,
        0,
        (SOFT_BLACK, colors.HexColor("#000000")),
        extend=True,
    )
    canvas.shade(shading)
    canvas.restoreState()


def save_pdf_resume(text: str, output_path: Path) -> None:
    normalized = normalize_dashes(text)
    base_resume = load_base_resume_data()
    sections = parse_resume_into_sections(normalized)
    name = extract_name(normalized, base_resume)

    name_style = ParagraphStyle(
        "NameStyle",
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=8,
        textColor=SOFT_WHITE,
        bulletColor=SOFT_WHITE,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=16,
        alignment=TA_LEFT,
        spaceBefore=12,
        spaceAfter=6,
        textColor=SOFT_WHITE,
        bulletColor=SOFT_WHITE,
    )
    body_style = ParagraphStyle(
        "BodyText",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=4,
        textColor=SOFT_WHITE,
        bulletColor=SOFT_WHITE,
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="normal",
    )
    dark_page = PageTemplate(id="DarkPage", frames=[frame], onPage=draw_gradient_bg)
    doc.addPageTemplates(dark_page)
    doc.pageTemplates = [dark_page]

    story: list = [Paragraph(name, name_style), Spacer(1, 6)]
    combined_sections: dict[str, list[str]] = {}

    def fallback_lines(heading: str) -> list[str]:
        if heading == "SUMMARY":
            return build_summary_lines(base_resume)
        if heading == "Key Skills":
            return build_skills_lines(base_resume)
        if heading == "Recent Achievements":
            return build_achievements_lines(base_resume)
        if heading == "Professional Experience":
            return build_experience_lines(base_resume)
        if heading == "EDUCATION":
            return build_education_lines(base_resume)
        if heading == "Certifications":
            return build_certifications_lines(base_resume)
        if heading == "References":
            return build_references_lines(base_resume)
        return []

    for heading in ORDERED_SECTIONS:
        combined_sections[heading] = sections.get(heading) or fallback_lines(heading)

    def append_section(section_heading: str, section_lines: list[str]) -> None:
        if not section_lines:
            return
        story.append(Paragraph(section_heading, heading_style))
        bullets: list[str] = []
        for line in section_lines:
            if re.match(r"^[-•]\s+", line):
                bullets.append(line)
                continue
            _flush_bullets(bullets, story, body_style)
            bullets.clear()
            story.append(Paragraph(line, body_style))
        _flush_bullets(bullets, story, body_style)

    for heading in ORDERED_SECTIONS:
        append_section(heading, combined_sections.get(heading, []))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story, onFirstPage=draw_gradient_bg, onLaterPages=draw_gradient_bg)


def save_cover_letter_pdf(text: str, output_path: Path) -> None:
    normalized = normalize_dashes(text)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="cover_letter",
    )
    dark_page = PageTemplate(id="CoverLetterDarkPage", frames=[frame], onPage=draw_gradient_bg)
    doc.addPageTemplates(dark_page)
    doc.pageTemplates = [dark_page]

    body_style = ParagraphStyle(
        "CoverLetterBody",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=4,
        textColor=SOFT_WHITE,
        bulletColor=SOFT_WHITE,
    )
    story: list = []
    bullets: list[str] = []
    for raw_line in normalized.replace("\r", "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            _flush_bullets(bullets, story, body_style)
            bullets.clear()
            if story:
                story.append(Spacer(1, 6))
            continue
        if re.match(r"^[-•]\s+", stripped):
            bullets.append(stripped)
            continue
        _flush_bullets(bullets, story, body_style)
        bullets.clear()
        story.append(Paragraph(stripped, body_style))
    _flush_bullets(bullets, story, body_style)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story, onFirstPage=draw_gradient_bg, onLaterPages=draw_gradient_bg)


def save_job_description_pdf(text: str, output_path: Path) -> None:
    """Save the clipboard job description as a PDF using cover letter styling."""
    save_cover_letter_pdf(text, output_path)


def save_output(target: Path, contents: str, logger: logging.Logger) -> None:
    target.write_text(contents, encoding="utf-8")
    logger.info("Saved %s", target)
    if (
        RESUME_TEXT_OUTPUT_PATH is not None
        and PDF_OUTPUT_PATH is not None
        and target == RESUME_TEXT_OUTPUT_PATH
    ):
        save_pdf_resume(contents, PDF_OUTPUT_PATH)


def ensure_openai_module(logger: logging.Logger) -> None:
    if OpenAI is None:
        logger.error("OpenAI import failed: %s", OPENAI_IMPORT_ERROR)
        raise RuntimeError(
            "The OpenAI Python SDK is not available. Install it with `py -m pip install openai`."
        )


def main() -> int:
    try:
        config = load_config(CONFIG_PATH)
    except Exception as exc:  # pragma: no cover
        print(f"Failed to load config: {exc}", file=sys.stderr)
        return 1

    logger = configure_logger(config)
    global RESUME_TEXT_OUTPUT_PATH, PDF_OUTPUT_PATH, COVER_LETTER_PDF_PATH, JOB_DESCRIPTION_PDF_PATH, JOB_ID
    RESUME_TEXT_OUTPUT_PATH = ROOT_DIR / config["output_resume_path"]
    PDF_OUTPUT_PATH = ROOT_DIR / config["output_resume_pdf_path"]
    JOB_ID = PDF_OUTPUT_PATH.stem if PDF_OUTPUT_PATH else None
    COVER_LETTER_PDF_PATH = (
        ROOT_DIR / f"CoverLetter_{JOB_ID}.pdf" if JOB_ID else None
    )
    JOB_DESCRIPTION_PDF_PATH = (
        ROOT_DIR / f"JobDescription_{JOB_ID}.pdf" if JOB_ID else None
    )
    try:
        sheet_config = load_sheet_config(config)
    except Exception as exc:  # pragma: no cover
        logger.error("Invalid sheet configuration: %s", exc)
        print("ERROR: Invalid sheet configuration; cannot continue.", file=sys.stderr)
        return 1

    start_time: Optional[float] = None

    try:
        ensure_openai_module(logger)
        try:
            job_description = get_job_description_from_clipboard().strip()
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to load job description: %s", exc)
            print("ERROR: Failed to load job description; cannot continue without it.", file=sys.stderr)
            return 1
        if not job_description:
            logger.error("Job description is empty; aborting resume generation.")
            print("ERROR: Job description is empty; aborting resume generation.", file=sys.stderr)
            return 1
        start_time = time.perf_counter()
        try:
            credentials = load_service_account_credentials()
            spreadsheet_id = _required_config_value(config, "spreadsheet_id")
            context = resolve_marker_context(credentials, spreadsheet_id, logger)
            worksheet = context.worksheet
            headers = _collect_header_indices(worksheet, sheet_config, logger)
        except Exception as exc:  # pragma: no cover
            logger.error("Unable to establish worksheet context: %s", exc)
            print(f"ERROR: Unable to establish worksheet context: {exc}", file=sys.stderr)
            return 1

        marker_row_number = context.row_index
        requested_row = _get_env_int("RESUME_SHEET_ROW")
        if requested_row is not None:
            row_number = requested_row
            logger.debug(
                "Using provided spreadsheet row %s in worksheet '%s' (marker row is %s)",
                row_number,
                context.title,
                marker_row_number,
            )
        else:
            row_number = marker_row_number
            logger.info(
                "Using marker row %s from column B in worksheet '%s'",
                row_number,
                context.title,
            )
        if JOB_DESCRIPTION_PDF_PATH:
            try:
                save_job_description_pdf(job_description, JOB_DESCRIPTION_PDF_PATH)
                logger.info("Saved %s", JOB_DESCRIPTION_PDF_PATH)
            except Exception as exc:  # pragma: no cover
                logger.error("Failed to save job description PDF: %s", exc)
                print("ERROR: Failed to save job description PDF.", file=sys.stderr)
                return 1
        base_resume_path = BOT_ASSETS_DIR / config["base_resume_path"]
        base_resume = load_json(base_resume_path)
        payload = generate_documents(base_resume, job_description, config, logger)
        resume_output = RESUME_TEXT_OUTPUT_PATH
        cover_letter_output = ROOT_DIR / config["output_cover_letter_path"]
        save_output(resume_output, payload["resume"], logger)
        save_output(cover_letter_output, payload["cover_letter"], logger)
        if COVER_LETTER_PDF_PATH:
            save_cover_letter_pdf(payload["cover_letter"], COVER_LETTER_PDF_PATH)
            logger.info("Saved %s", COVER_LETTER_PDF_PATH)
        if (
            PDF_OUTPUT_PATH
            and PDF_OUTPUT_PATH.exists()
            and COVER_LETTER_PDF_PATH
            and COVER_LETTER_PDF_PATH.exists()
            and JOB_DESCRIPTION_PDF_PATH
            and JOB_DESCRIPTION_PDF_PATH.exists()
        ):
            try:
                upload_pdfs_and_update_sheet(
                    worksheet,
                    headers,
                    row_number,
                    PDF_OUTPUT_PATH,
                    COVER_LETTER_PDF_PATH,
                    JOB_DESCRIPTION_PDF_PATH,
                    sheet_config,
                    logger,
                )
            except Exception as exc:  # pragma: no cover
                logger.exception("Drive upload or sheet update failed: %s", exc)
                print("ERROR: Failed to upload PDFs to Drive; see logs for details.", file=sys.stderr)
                return 1
        logger.info("Resume Engine completed successfully.")
        if PDF_OUTPUT_PATH and PDF_OUTPUT_PATH.exists():
            print(f"[PDF LINK] /view/{PDF_OUTPUT_PATH.name}")
        if COVER_LETTER_PDF_PATH and COVER_LETTER_PDF_PATH.exists():
            print(f"[PDF COVER LETTER] /view/{COVER_LETTER_PDF_PATH.name}")
        elapsed = time.perf_counter() - (start_time or time.perf_counter())
        return 0
    except Exception as exc:  # pragma: no cover
        logger.exception("Resume Engine failed: %s", exc)
        print(f"Resume Engine failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
