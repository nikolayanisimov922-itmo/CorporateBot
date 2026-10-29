"""Раздел «📈 Управление»: чтение таблиц руководителей (только чтение) и кэш.

Три таблицы: мастер-таблица проектов, план-факт, найм. Каждая таблица читается
ОДНИМ запросом (values_batch_get по нужным листам) и кэшируется в памяти на
5 минут — лимит Sheets API (~60 чтений в минуту) не страшен.

Все функции блокирующие — вызывать через asyncio.to_thread.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import threading
import time

from app.expenses import DUBAI, MONTHS_RU

CACHE_TTL = 5 * 60

PROJECTS = "projects"
PLAN = "plan"
HIRING = "hiring"

TABLE_TITLES = {
    PROJECTS: "Мастер-таблица проектов",
    PLAN: "План-факт",
    HIRING: "Найм",
}
TABLE_ENV = {
    PROJECTS: "MGMT_PROJECTS_SHEET_ID",
    PLAN: "MGMT_PLAN_SHEET_ID",
    HIRING: "MGMT_HIRING_SHEET_ID",
}

# Листы мастер-таблицы, без которых раздел «Проекты» не посчитать.
PROJECT_SHEETS = [
    "Общая таблица",
    "Отдел разработки",
    "Загрузка (отдел разработки)",
    "Отдел реализации",
    "Загрузка отдела реализации",
    "Отдел комплектации",
    "Загрузка отдела комплектации",
]

MONTHS_EN = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def plan_sheet_name(month: int) -> str:
    """«ПЛАН НОЯБРЬ» — так называются листы в таблице план-факта."""
    return f"ПЛАН {MONTHS_RU[month - 1].upper()}"


def hiring_sheet_name(month: int) -> str:
    """«november» — так называются листы в таблице найма."""
    return MONTHS_EN[month - 1]


def _norm(title: str) -> str:
    return " ".join(str(title).split()).casefold()


def find_title(titles: list[str], wanted: str) -> str | None:
    """Лист по названию без учёта регистра и лишних пробелов."""
    w = _norm(wanted)
    return next((t for t in titles if _norm(t) == w), None)


def _a1_sheet(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def read_tables(ss, titles: list[str] | None = None) -> dict[str, list[list]]:
    """Все (или указанные) листы таблицы одним запросом: {лист: строки}."""
    if titles is None:
        titles = [ws.title for ws in ss.worksheets()]
    if not titles:
        return {}
    resp = ss.values_batch_get(
        ranges=[_a1_sheet(t) for t in titles],
        params={
            "valueRenderOption": "UNFORMATTED_VALUE",
            "dateTimeRenderOption": "FORMATTED_STRING",
        },
    )
    out = {}
    for title, vr in zip(titles, resp.get("valueRanges", [])):
        out[title] = vr.get("values", [])
    return out


class SheetCache:
    """Кэш таблиц в памяти: {ключ таблицы: (время чтения, {лист: строки})}."""

    def __init__(self, ttl: int = CACHE_TTL) -> None:
        self.ttl = ttl
        self._data: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def get(self, sheets, key: str, sheet_id: str, force: bool = False):
        """(листы, время чтения по Дубаю, свежие ли данные).

        Если обновить не удалось, а старые данные есть — отдаём их со
        stale=True; если данных нет совсем — пробрасываем ошибку.
        """
        with self._lock:
            cached = self._data.get(key)
            if cached and not force and time.time() - cached[0] < self.ttl:
                return cached[1], _dubai(cached[0]), True
            try:
                data = read_tables(sheets.spreadsheet(sheet_id))
            except Exception:
                if cached:
                    logging.exception("Управление: не удалось обновить %s, отдаю кэш", key)
                    return cached[1], _dubai(cached[0]), False
                raise
            self._data[key] = (time.time(), data)
            return data, _dubai(self._data[key][0]), True


def _dubai(ts: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, DUBAI)


def _filled_rows(rows: list[list]) -> int:
    return sum(1 for r in rows if any(str(c).strip() for c in r))


def ping(sheets, sheet_ids: dict[str, str], today: dt.date) -> list[str]:
    """Проверка доступа ко всем таблицам и листам. Строки отчёта для админа."""
    lines: list[str] = []
    for key in (PROJECTS, PLAN, HIRING):
        title = TABLE_TITLES[key]
        sheet_id = sheet_ids.get(key)
        if not sheet_id:
            lines.append(f"❌ <b>{title}</b>: не задан {TABLE_ENV[key]} в .env")
            lines.append("")
            continue
        try:
            ss = sheets.spreadsheet(sheet_id)
            data = read_tables(ss)
        except Exception as err:  # noqa: BLE001
            lines.append(
                f"❌ <b>{title}</b>: "
                + html.escape(sheets.explain_error(err, role="Читатель"))
            )
            lines.append("")
            continue
        names = list(data)
        lines.append(f"✅ <b>{title}</b> «{html.escape(ss.title)}» — листов: {len(names)}")
        for name in names:
            lines.append(f"   • {html.escape(name)} — строк: {_filled_rows(data[name])}")

        if key == PROJECTS:
            for need in PROJECT_SHEETS:
                found = find_title(names, need)
                if not found:
                    lines.append(f"   ❌ нет листа «{need}»")
                elif not _filled_rows(data[found]):
                    lines.append(f"   ⚠️ лист «{need}» пустой")
        elif key == PLAN:
            if not any(_norm(n).startswith("план ") for n in names):
                lines.append("   ❌ нет ни одного листа «ПЛАН <МЕСЯЦ>»")
            cur = plan_sheet_name(today.month)
            if not find_title(names, cur):
                lines.append(f"   ⚠️ нет листа текущего месяца «{cur}»")
        elif key == HIRING:
            cur = hiring_sheet_name(today.month)
            if not find_title(names, cur):
                lines.append(f"   ⚠️ нет листа текущего месяца «{cur}»")
        lines.append("")
    return lines
