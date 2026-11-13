"""«🌴 Мой отпуск»: разбор корпоративной таблицы отпусков (чистые функции, без сети).

Таблица (Google, ведёт HR):
  • листы месяцев «January 2026» … «December 2026»: строка на сотрудника (ФИО в
    колонке B), колонка на день (строка с числами 1..31), в ячейках коды:
    H — отпуск (1), H1/H2 — полдня (0,5), Q — четверть дня (0,25), E — прочее за
    счёт отпуска (1); S больничный, M декрет, L отгул, W удалёнка, C семейные — не
    списываются;
  • лист «Totals»: Base allowance | Carry over | Total allowance | Absence count |
    Remaining allowance | разбивка по типам. Цифры берём ОТСЮДА — это официальный итог HR.
Отпуск, уже отмеченный в будущих датах, вычтен из «Remaining» — его показываем
отдельно как «запланировано».

Кто есть кто: колонка «Telegram» на листе «Totals» (если HR её добавит) → привязка
админа (/vac_link) → однозначное совпадение имени из Telegram с ФИО из таблицы.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib
import re
from dataclasses import dataclass, field

from app.management_data import cell, norm, to_num

# Коды отметок: (что это, сколько дней списывается с отпуска).
CODES = {
    "H": ("отпуск", 1.0),
    "H1": ("полдня (утро)", 0.5),
    "H2": ("полдня (после обеда)", 0.5),
    "Q": ("четверть дня", 0.25),
    "E": ("за счёт отпуска", 1.0),
    "S": ("больничный", 0.0),
    "M": ("декрет", 0.0),
    "L": ("отгул за переработку", 0.0),
    "W": ("удалёнка", 0.0),
    "C": ("по семейным обстоятельствам", 0.0),
}
VACATION_CODES = {"H", "H1", "H2", "Q", "E"}  # то, что списывается с отпуска

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
_MONTH_TITLE = re.compile(r"^\s*([A-Za-z]+)\s+(\d{4})\s*$")

LINKS_FILE = pathlib.Path("data") / "vacation_links.json"


@dataclass
class Employee:
    name: str  # ФИО как в таблице
    base: float | None = None
    carry: float | None = None
    total: float | None = None
    used: float | None = None  # Absence count — списано с отпуска (вкл. запланированное)
    remaining: float | None = None
    breakdown: dict = field(default_factory=dict)  # «Holiday»: 4, «Sickness»: 1 …
    telegram: str = ""  # из колонки «Telegram», если есть
    days: dict = field(default_factory=dict)  # дата → код (по листам месяцев)


@dataclass
class VacationData:
    year: int | None
    employees: dict[str, Employee]  # норм. ФИО → сотрудник
    issues: list[str]


def _name_key(name: str) -> str:
    return " ".join(sorted(norm(name).replace("ё", "е").split()))


def parse_totals(rows: list[list], issues: list[str]) -> dict[str, Employee]:
    h = None
    for i, row in enumerate(rows[:10]):
        heads = [norm(c) for c in row]
        if any("remaining" in x for x in heads):
            h = i
            break
    if h is None:
        issues.append("«Totals»: не нашёл строку заголовков (Remaining allowance)")
        return {}
    heads = [norm(c) for c in rows[h]]

    def col(*names):
        for n in names:
            for j, x in enumerate(heads):
                if x.startswith(n):
                    return j
        return None

    c_base, c_carry = col("base allowance"), col("carry over")
    c_total, c_used = col("total allowance"), col("absence count")
    c_rem, c_tg = col("remaining allowance", "remaining"), col("telegram", "телеграм")
    # ФИО — колонка левее «Base allowance» (обычно B).
    c_name = (c_base - 1) if c_base else 1
    breakdown_cols = {
        j: str(rows[h][j]).strip()
        for j in range((c_rem or 0) + 1, len(rows[h]))
        if str(rows[h][j] or "").strip() and j != c_tg
    }
    out: dict[str, Employee] = {}
    for row in rows[h + 1:]:
        name = str(cell(row, c_name) or "").strip()
        if not name:
            continue
        if len(name) > 60:  # пояснения/ссылки внизу листа
            continue
        e = Employee(
            name=name,
            base=to_num(cell(row, c_base)),
            carry=to_num(cell(row, c_carry)),
            total=to_num(cell(row, c_total)),
            used=to_num(cell(row, c_used)),
            remaining=to_num(cell(row, c_rem)),
            telegram=str(cell(row, c_tg) or "").strip().lstrip("@") if c_tg is not None else "",
        )
        for j, label in breakdown_cols.items():
            v = to_num(cell(row, j))
            if v:
                e.breakdown[label] = v
        out[_name_key(name)] = e
    return out


def parse_month(title: str, rows: list[list], employees: dict[str, Employee], issues: list[str]) -> int | None:
    """Отметки листа месяца → Employee.days. Возвращает год листа."""
    m = _MONTH_TITLE.match(title)
    if not m or m.group(1).lower() not in MONTHS:
        return None
    month, year = MONTHS.index(m.group(1).lower()) + 1, int(m.group(2))
    # Строка с числами месяца: 1, 2, 3 подряд.
    day_row = None
    for i, row in enumerate(rows[:10]):
        nums = [to_num(c) for c in row]
        for j in range(len(nums) - 2):
            if nums[j] == 1 and nums[j + 1] == 2 and nums[j + 2] == 3:
                day_row, first_col = i, j
                break
        if day_row is not None:
            break
    if day_row is None:
        issues.append(f"«{title}»: не нашёл строку с числами месяца")
        return year
    day_cols = {}
    for j in range(first_col, len(rows[day_row])):
        d = to_num(rows[day_row][j])
        if d is None or not 1 <= d <= 31:
            break
        try:
            day_cols[j] = dt.date(year, month, int(d))
        except ValueError:
            break
    for row in rows[day_row + 1:]:
        name = str(cell(row, 1) or "").strip()
        e = employees.get(_name_key(name)) if name else None
        if e is None:
            continue
        for j, d in day_cols.items():
            code = str(cell(row, j) or "").strip().upper()
            if code in CODES:
                e.days[d] = code
            elif code:
                issues.append(f"«{title}», {name}, {d:%d.%m}: непонятный код «{code}»")
    return year


def parse_vacation(data: dict) -> VacationData:
    issues: list[str] = []
    totals_title = next((t for t in data if norm(t) == "totals"), None)
    if totals_title is None:
        return VacationData(None, {}, ["нет листа «Totals»"])
    employees = parse_totals(data[totals_title], issues)
    years = []
    for title, rows in data.items():
        if title == totals_title:
            continue
        y = parse_month(title, rows, employees, issues)
        if y:
            years.append(y)
    year = max(set(years), key=years.count) if years else None
    return VacationData(year, employees, issues)


# --- кто есть кто ---------------------------------------------------------------

def load_links() -> dict[str, str]:
    try:
        return json.loads(LINKS_FILE.read_text(encoding="utf-8")) if LINKS_FILE.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_link(user_id: int, table_name: str) -> None:
    links = load_links()
    links[str(user_id)] = table_name
    try:
        LINKS_FILE.parent.mkdir(exist_ok=True)
        LINKS_FILE.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logging.exception("Не удалось сохранить %s", LINKS_FILE)


def find_employee(vd: VacationData, user_id: int, username: str, full_name: str) -> Employee | None:
    # 1) колонка «Telegram» в таблице (ник или числовой ID)
    u = (username or "").lower()
    for e in vd.employees.values():
        tg = e.telegram.lower()
        if tg and (tg == u or tg == str(user_id)):
            return e
    # 2) привязка админа
    linked = load_links().get(str(user_id))
    if linked:
        return vd.employees.get(_name_key(linked))
    # 3) имя в Telegram однозначно совпадает с ФИО (все слова из Telegram есть в ФИО)
    words = set(_name_key(full_name).split())
    if len(words) >= 2:
        hits = [e for e in vd.employees.values() if words <= set(_name_key(e.name).split())]
        if len(hits) == 1:
            return hits[0]
    return None


def match_name(vd: VacationData, text: str) -> Employee | None:
    """Для /vac_link: сотрудник по ФИО (порядок слов и регистр не важны, можно часть)."""
    words = set(_name_key(text).split())
    if not words:
        return None
    exact = vd.employees.get(_name_key(text))
    if exact:
        return exact
    hits = [e for e in vd.employees.values() if words <= set(_name_key(e.name).split())]
    return hits[0] if len(hits) == 1 else None


# --- даты ----------------------------------------------------------------------

def ranges(e: Employee, codes: set[str], start: dt.date | None = None,
           end: dt.date | None = None) -> list[tuple[dt.date, dt.date, float]]:
    """Подряд идущие дни с указанными кодами → [(с, по, сколько дней списано)]."""
    days = sorted(d for d, c in e.days.items() if c in codes
                  and (start is None or d >= start) and (end is None or d <= end))
    out: list[list] = []
    for d in days:
        w = CODES[e.days[d]][1]
        if out and (d - out[-1][1]).days == 1:
            out[-1][1] = d
            out[-1][2] += w
        else:
            out.append([d, d, w])
    return [(a, b, w) for a, b, w in out]


def fmt_num(x: float | None) -> str:
    if x is None:
        return "—"
    return str(int(x)) if float(x).is_integer() else f"{x:g}".replace(".", ",")


def fmt_range(a: dt.date, b: dt.date, w: float, lang: str) -> str:
    span = f"{a:%d.%m}" if a == b else f"{a:%d.%m}–{b:%d.%m}"
    unit = "дн." if lang != "en" else ("day" if w == 1 else "days")
    return f"{span} ({fmt_num(w)} {unit})"
