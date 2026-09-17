"""Этап 7: запись данных в Google Sheets через сервисный аккаунт."""
from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClient:
    def __init__(self, credentials_file: str, sheet_id: str) -> None:
        creds = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
        self._gc = gspread.authorize(creds)
        self._sheet = self._gc.open_by_key(sheet_id)

    def append_row(self, worksheet_name: str, header: list[str], row: list[str]) -> None:
        """Добавляет строку на нужный лист. Лист и шапку создаёт при необходимости.

        Блокирующий вызов — запускать через asyncio.to_thread.
        """
        try:
            ws = self._sheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            ws = self._sheet.add_worksheet(
                title=worksheet_name, rows=1000, cols=max(10, len(header))
            )
            ws.append_row(header, value_input_option="USER_ENTERED")

        # Если лист пустой — сначала пишем шапку.
        if not ws.row_values(1):
            ws.append_row(header, value_input_option="USER_ENTERED")

        ws.append_row(row, value_input_option="USER_ENTERED")
