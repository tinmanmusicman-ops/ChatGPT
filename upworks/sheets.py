from __future__ import annotations

import re
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build


class SheetsError(RuntimeError):
    pass


CANONICAL_ALIASES: dict[str, list[str]] = {
    "timestamp": ["Timestamp", "Evaluation Timestamp"],
    "message_id": ["Message ID", "MessageID", "MessagID", "message_id"],
    "job_url": ["Job URL", "URL", "Job Link"],
    "job_description": ["Short Description", "Job Description", "Description"],
    "ai_decision": ["AI Decision", "Do Bid", "do Bid"],
    "score": ["Score", "AI Score", "Total Score", "total_score"],
    "complexity": ["Complexity"],
    "confidence": ["Confidence"],
    "reason": ["Reason", "AI Reason"],
    "price": ["Price"],
    "source": ["_source", "Source"],
}


class SheetsClient:
    def __init__(
        self,
        service_account_info: dict[str, str],
        spreadsheet_id: str,
        worksheet_name: str,
        message_id_column: str,
    ) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._message_id_column = message_id_column

        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._sheet_id = self._load_sheet_id()
        self._header = self._load_header()
        self._header_index = {name: idx for idx, name in enumerate(self._header)}
        self._resolved_columns = self._resolve_columns()
        self._validate_columns()

    def _load_sheet_id(self) -> int:
        metadata = (
            self._service.spreadsheets()
            .get(spreadsheetId=self._spreadsheet_id, fields="sheets(properties(sheetId,title))")
            .execute()
        )
        for sheet in metadata.get("sheets", []):
            props = sheet.get("properties", {})
            if str(props.get("title", "")).strip() == self._worksheet_name:
                return int(props["sheetId"])
        raise SheetsError(f"Worksheet '{self._worksheet_name}' not found in spreadsheet metadata")

    def _load_header(self) -> list[str]:
        result = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self._spreadsheet_id, range=f"{self._worksheet_name}!1:1")
            .execute()
        )
        rows = result.get("values", [])
        if not rows or not rows[0]:
            raise SheetsError("Worksheet header row is missing")
        return [str(col).strip() for col in rows[0]]

    def _resolve_columns(self) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for canonical, aliases in CANONICAL_ALIASES.items():
            for alias in aliases:
                if alias in self._header_index:
                    resolved[canonical] = alias
                    break
        return resolved

    def _validate_columns(self) -> None:
        if self._message_id_column in self._header_index:
            self._resolved_columns["message_id"] = self._message_id_column
        elif "message_id" not in self._resolved_columns:
            raise SheetsError(
                f"Worksheet missing message id column. Tried explicit '{self._message_id_column}' and aliases "
                f"{', '.join(CANONICAL_ALIASES['message_id'])}"
            )

        required_logical = ["timestamp", "job_url", "job_description", "ai_decision"]
        missing = [name for name in required_logical if name not in self._resolved_columns]
        if missing:
            raise SheetsError(f"Worksheet missing required logical columns: {', '.join(missing)}")

    def get_existing_message_ids(self) -> set[str]:
        result = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self._spreadsheet_id, range=f"{self._worksheet_name}!A:Z")
            .execute()
        )
        rows: list[list[Any]] = result.get("values", [])
        if not rows:
            return set()

        message_id_col = self._resolved_columns["message_id"]
        message_id_idx = self._header_index[message_id_col]
        existing: set[str] = set()
        for row in rows[1:]:
            if len(row) <= message_id_idx:
                continue
            value = str(row[message_id_idx]).strip()
            if value:
                existing.add(value)
        return existing

    def append_rows(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            return

        values: list[list[str]] = []
        description_notes: list[str] = []
        price_notes: list[str] = []
        for row_data in rows:
            row = [""] * len(self._header)
            for key, value in row_data.items():
                column_name = self._resolved_columns.get(key)
                if not column_name:
                    continue
                row[self._header_index[column_name]] = value
            values.append(row)
            description_notes.append(str(row_data.get("job_description_note", "")).strip())
            price_notes.append(str(row_data.get("price_note", "")).strip())

        body = {"values": values}
        append_result = (
            self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=f"{self._worksheet_name}!A1",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )

        self._apply_column_notes(append_result, "job_description", description_notes)
        self._apply_column_notes(append_result, "price", price_notes)

    def _apply_column_notes(self, append_result: dict[str, Any], logical_column: str, notes: list[str]) -> None:
        if not any(notes):
            return

        target_col = self._resolved_columns.get(logical_column)
        if not target_col:
            raise SheetsError(f"Cannot write notes: {logical_column} column is not resolved")
        target_col_idx = self._header_index[target_col]

        updated_range = str(append_result.get("updates", {}).get("updatedRange", "")).strip()
        # Example: "'Inbox'!A12:K13" or "Inbox!A2:K2"
        match = re.search(r"![A-Z]+(\d+)(?::[A-Z]+\d+)?$", updated_range)
        if not match:
            raise SheetsError(f"Unable to parse updatedRange from append response: {updated_range}")
        start_row_1based = int(match.group(1))

        requests = []
        for idx, note_text in enumerate(notes):
            if not note_text:
                continue
            row_index_0based = (start_row_1based - 1) + idx
            requests.append(
                {
                    "updateCells": {
                        "range": {
                            "sheetId": self._sheet_id,
                            "startRowIndex": row_index_0based,
                            "endRowIndex": row_index_0based + 1,
                            "startColumnIndex": target_col_idx,
                            "endColumnIndex": target_col_idx + 1,
                        },
                        "rows": [{"values": [{"note": note_text}]}],
                        "fields": "note",
                    }
                }
            )

        if not requests:
            return

        self._service.spreadsheets().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={"requests": requests},
        ).execute()
