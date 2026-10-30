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
        # Почта сервисного аккаунта — её нужно добавить в таблицу как «Редактор».
        self.email: str = getattr(creds, "service_account_email", "") or ""
        self._gc = gspread.authorize(creds)
        self._cache: dict[str, gspread.Spreadsheet] = {}

    def spreadsheet(self, spreadsheet_id: str):
        """Открытая таблица gspread (кэшируется). Блокирующий вызов."""
        return self._spreadsheet(spreadsheet_id)

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

    def explain_error(self, err: Exception, role: str = "Редактор") -> str:
        """Понятное объяснение ошибки Google Sheets для администратора."""
        status = getattr(getattr(err, "response", None), "status_code", None)
        if isinstance(err, gspread.SpreadsheetNotFound) or status == 404:
            return (
                "Таблица не найдена. Проверьте ID в .env (кусок ссылки между /d/ "
                "и /edit) и что почта бота добавлена в таблицу:\n" + self.email
            )
        # gspread при открытии таблицы превращает ответ 403 в PermissionError без текста.
        if status == 403 or isinstance(err, PermissionError):
            return (
                "У бота нет доступа к таблице. Откройте таблицу → «Настройки "
                "доступа» → добавьте эту почту с правами «" + role + "»:\n" + self.email
            )
        if status == 429:
            return "Google временно ограничил число запросов к таблицам — пройдёт само через минуту."
        return f"{type(err).__name__}: {err}"[:500]
