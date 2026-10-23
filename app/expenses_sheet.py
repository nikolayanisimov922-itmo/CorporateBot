"""Запись план/факта в Google-таблицу.

Лист месяца «Ноябрь 2026» — сводка для быстрого чтения (как в образце):
  слева комплектаторы — по столбцу на человека, строки «План (02.11)» /
  «Факт (06.11)» на каждую неделю; справа ПМ — «План (начало месяца)» /
  «Факт (конец месяца)». В ячейке — итог, присланный сотрудником.
Лист «Ноябрь 2026 — детали» — каждая строка каждого проекта; ничего не
  стирается: при исправлении прежние строки помечаются «заменено».

Все функции блокирующие — вызывать через asyncio.to_thread.
"""
from __future__ import annotations

import datetime as dt
import threading

import gspread
from gspread.utils import rowcol_to_a1

from app import expenses

from app.expenses import (
    KIND_RU,
    KOMPLEKT,
    MONTHS_RU,
    PLAN,
    PM,
    ROLE_RU,
    Period,
    fmt_amount,
    members,
)

DETAILS_HEADER = [
    "Дата отправки", "Сотрудник", "Отдел", "План/Факт", "Период",
    "Проект", "Сумма, AED", "Статус",
]
TEST_WORKSHEET = "Тест"
ACTUAL = "актуально"

# Одна запись за раз: два сотрудника одновременно не создадут лист дважды.
_lock = threading.Lock()


def month_title(year: int, month: int) -> str:
    return f"{MONTHS_RU[month - 1]} {year}"


def _mondays(year: int, month: int) -> list[dt.date]:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(7 - d.weekday()) % 7)
    out = []
    while d.month == month:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def _week_rows(monday: dt.date) -> tuple[int, int]:
    """Строки «План» и «Факт» недели: по 3 строки на неделю (план, факт, пусто)."""
    k = (monday.day - 1) // 7
    return 2 + 3 * k, 3 + 3 * k


def _komplekt_col(i: int) -> int:
    return 2 + i  # B, C, D, E…


def _pm_label_col() -> int:
    return 2 + len(members(KOMPLEKT)) + 1  # через один пустой столбец


def _pm_col(j: int) -> int:
    return _pm_label_col() + 1 + j


def cell_for(name: str, role: str, period: Period) -> str:
    if role == KOMPLEKT:
        i = [m["name"] for m in members(KOMPLEKT)].index(name)
        plan_row, fact_row = _week_rows(period.monday)
        row = plan_row if period.kind == PLAN else fact_row
        return rowcol_to_a1(row, _komplekt_col(i))
    j = [m["name"] for m in members(PM)].index(name)
    return rowcol_to_a1(2 if period.kind == PLAN else 3, _pm_col(j))


def _layout(year: int, month: int) -> list[list[str]]:
    k_names = [m["name"] for m in members(KOMPLEKT)]
    p_names = [m["name"] for m in members(PM)]
    width = _pm_col(len(p_names) - 1)
    mondays = _mondays(year, month)
    height = max(3, _week_rows(mondays[-1])[1]) if mondays else 3
    grid = [[""] * width for _ in range(height)]
    for i, n in enumerate(k_names):
        grid[0][_komplekt_col(i) - 1] = n
    for j, n in enumerate(p_names):
        grid[0][_pm_col(j) - 1] = n
    for mon in mondays:
        plan_row, fact_row = _week_rows(mon)
        grid[plan_row - 1][0] = f"План ({mon:%d.%m})"
        grid[fact_row - 1][0] = f"Факт ({mon + dt.timedelta(days=4):%d.%m})"
    grid[1][_pm_label_col() - 1] = "План (начало месяца)"
    grid[2][_pm_label_col() - 1] = "Факт (конец месяца)"
    return grid


def _num(x: float) -> float | int:
    """15000.0 → 15000: целые суммы пишем без «.0»."""
    x = round(x, 2)
    return int(x) if float(x).is_integer() else x


def _try(fn, *args, **kwargs) -> None:
    """Оформление — приятное дополнение: его ошибка не должна мешать записи."""
    try:
        fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        pass


def _ensure_month(ss, year: int, month: int):
    title = month_title(year, month)
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        pass
    grid = _layout(year, month)
    ws = ss.add_worksheet(title=title, rows=max(40, len(grid) + 5), cols=len(grid[0]) + 3)
    ws.update(values=grid, range_name="A1", value_input_option="RAW")
    end = rowcol_to_a1(len(grid), len(grid[0]))
    _try(ws.format, f"A1:{rowcol_to_a1(1, len(grid[0]))}", {"textFormat": {"bold": True}})
    _try(ws.format, f"A1:A{len(grid)}", {"textFormat": {"bold": True}})
    label = rowcol_to_a1(1, _pm_label_col())[:-1]
    _try(ws.format, f"{label}1:{label}3", {"textFormat": {"bold": True}})
    _try(ws.format, f"B2:{end}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    _try(ws.freeze, rows=1, cols=1)
    return ws


def _ensure_details(ss, title: str):
    try:
        ws = ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=500, cols=len(DETAILS_HEADER))
        ws.update(values=[DETAILS_HEADER], range_name="A1", value_input_option="RAW")
        _try(ws.format, "A1:H1", {"textFormat": {"bold": True}})
        _try(ws.format, "G:G", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})
        _try(ws.freeze, rows=1)
    return ws


def write_submission(
    ss,
    member: dict,
    period: Period,
    items: list[tuple[str, float]],
    total: float,
    previous_total: float | None,
    test: bool = False,
) -> None:
    """Пишет отправку: итог в лист месяца (кроме теста) и строки в детали."""
    now = expenses.now_dubai().strftime("%d.%m.%Y %H:%M")
    kind_ru = KIND_RU[period.kind]
    with _lock:
        if not test:
            ws = _ensure_month(ss, period.year, period.month)
            cell = cell_for(member["name"], member["role"], period)
            ws.update(values=[[_num(total)]], range_name=cell, value_input_option="RAW")
            if previous_total is not None:
                _try(
                    ws.update_note,
                    cell,
                    f"Исправлено {now}. Было: {fmt_amount(previous_total)} AED",
                )
            details_title = f"{month_title(period.year, period.month)} — детали"
        else:
            details_title = TEST_WORKSHEET

        det = _ensure_details(ss, details_title)
        # Прежние строки этого же человека за этот же период — «заменено».
        rows = det.get_all_values()
        stale = [
            i + 1
            for i, r in enumerate(rows)
            if i > 0 and len(r) >= 8 and r[1] == member["name"] and r[3] == kind_ru
            and r[4] == period.label and r[7] == ACTUAL
        ]
        if stale:
            det.batch_update(
                [{"range": f"H{r}", "values": [[f"заменено {now}"]]} for r in stale],
                value_input_option="RAW",
            )
        role_ru = ROLE_RU[member["role"]]
        new_rows = [
            [now, member["name"], role_ru, kind_ru, period.label, p, _num(a), ACTUAL]
            for p, a in items
        ]
        det.append_rows(new_rows, value_input_option="RAW")


def ensure_current_month(ss, today: dt.date) -> None:
    """Создаёт лист нового месяца заранее (вызывается 1-го числа)."""
    with _lock:
        _ensure_month(ss, today.year, today.month)

