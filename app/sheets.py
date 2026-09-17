"""Этап 7: запись данных в Google Sheets через сервисный аккаунт.

Каждая форма может писать в свою таблицу (по её ID). Один сервисный аккаунт —
достаточно поделиться с ним каждой таблицей как редактором.
"""
from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClient:
    def __init__(self, credentials_file: str) -> None:
        creds = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
        self._gc = gspread.authorize(creds)
        self._cache: dict[str, gspread.Spreadsheet] = {}

    def _spreadsheet(self, spreadsheet_id: str):
        if spreadsheet_id not in self._cache:
            self._cache[spreadsheet_id] = self._gc.open_by_key(spreadsheet_id)
        return self._cache[spreadsheet_id]

    def append_row(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        header: list[str],
        row: list[str],
    ) -> None:
        """Добавляет строку в нужную таблицу/лист. Лист и шапку создаёт при необходимости.

        Блокирующий вызов — запускать через asyncio.to_thread.
        """
        sheet = self._spreadsheet(spreadsheet_id)
        try:
            ws = sheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            ws = sheet.add_worksheet(
                title=worksheet_name, rows=1000, cols=max(10, len(header))
            )
            ws.append_row(header, value_input_option="USER_ENTERED")

        if not ws.row_values(1):
            ws.append_row(header, value_input_option="USER_ENTERED")

        ws.append_row(row, value_input_option="USER_ENTERED")
