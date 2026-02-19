from __future__ import annotations

from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


def _col_to_a1(index: int) -> str:
    result = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


class GoogleSheetsClient:
    def __init__(self, credentials_file: str, spreadsheet_id: str, sheet_name: str) -> None:
        creds = Credentials.from_service_account_file(
            credentials_file,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self.service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name

    def _get_headers(self) -> list[str]:
        response = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=f"{self.sheet_name}!1:1")
            .execute()
        )
        values = response.get("values", [[]])
        return [str(v).strip() for v in values[0]]

    def read_row(self, row_number: int) -> dict[str, Any]:
        headers = self._get_headers()
        response = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=f"{self.sheet_name}!A{row_number}:ZZ{row_number}")
            .execute()
        )
        values = response.get("values", [[]])
        row_values = values[0] if values else []
        row_values = row_values + [""] * max(0, len(headers) - len(row_values))
        row = {headers[i]: row_values[i] for i in range(len(headers))}
        row["rowNumber"] = row_number
        return row

    def update_row_columns(self, row_number: int, updates: dict[str, Any]) -> dict[str, Any]:
        headers = self._get_headers()
        col_map = {header: i for i, header in enumerate(headers)}

        data = []
        ignored = []
        for key, value in updates.items():
            if key not in col_map:
                ignored.append(key)
                continue
            col = _col_to_a1(col_map[key])
            data.append(
                {
                    "range": f"{self.sheet_name}!{col}{row_number}",
                    "values": [[str(value) if value is not None else ""]],
                }
            )

        if data:
            (
                self.service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"valueInputOption": "USER_ENTERED", "data": data},
                )
                .execute()
            )

        return {"updated_keys": [d["range"] for d in data], "ignored_keys": ignored}

