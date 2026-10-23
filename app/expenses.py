"""План/факт расходов: команда, периоды, проверка формата, тексты, хранилище.

Комплектаторы сдают план в понедельник и факт в пятницу (неделя).
Проджект-менеджеры — план 1–2 числа и факт в последние 2 дня месяца (месяц).
Всё время — дубайское (UTC+4, без перехода на летнее время).
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import pathlib
import re
from dataclasses import dataclass

DUBAI = dt.timezone(dt.timedelta(hours=4))

KOMPLEKT = "komplekt"
PM = "pm"
PLAN = "plan"
FACT = "fact"

# Таблица «План/факт расходов». Можно переопределить в .env (GOOGLE_SHEET_EXPENSES).
DEFAULT_SHEET_ID = "1mfQTxzcpZAgDVdFZjWQFRbHRk3Zw70HHc7bB4uTOo7U"

# Порядок важен: в таком порядке идут столбцы на листе месяца.
TEAM: list[dict] = [
    {"username": "amiii1234", "name": "Ансия", "role": KOMPLEKT},
    {"username": "alenka_lykova", "name": "Алена", "role": KOMPLEKT},
    {"username": "sova_designed", "name": "Алина", "role": KOMPLEKT},
    {"username": "May_Magdy", "name": "May", "role": KOMPLEKT},
    {"username": "Vladimir_Belkanov", "name": "Владимир", "role": PM},
    {"username": "merimka9303", "name": "Меерим", "role": PM},
]

ROLE_RU = {KOMPLEKT: "Комплектация", PM: "Реализация"}
KIND_RU = {PLAN: "План", FACT: "Факт"}

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

FORMAT_EXAMPLE = (
    "381-03 Villa 29, Al Barsha — 12 500\n"
    "376-03 Unit A-01, Tower A, The Edge — 8 000"
)


def now_dubai() -> dt.datetime:
    return dt.datetime.now(DUBAI)


def members(role: str | None = None) -> list[dict]:
    return [m for m in TEAM if role is None or m["role"] == role]


def member_by_username(username: str | None) -> dict | None:
    if not username:
        return None
    u = username.lstrip("@").lower()
    for m in TEAM:
        if m["username"].lower() == u:
            return m
    return None


# --- периоды ----------------------------------------------------------------

def week_monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


@dataclass(frozen=True)
class Period:
    role: str
    kind: str
    key: str  # W2026-11-02 (неделя с понедельника) или M2026-11 (месяц)
    year: int  # месяц листа, на который попадает запись
    month: int
    monday: dt.date | None = None

    @property
    def label(self) -> str:
        """Подпись периода для людей и таблицы."""
        if self.monday:
            fri = self.monday + dt.timedelta(days=4)
            return f"неделя {self.monday:%d.%m}–{fri:%d.%m}"
        return f"{MONTHS_RU[self.month - 1]} {self.year}"

    @property
    def what_ru(self) -> str:
        if self.monday:
            return "план на эту неделю" if self.kind == PLAN else "факт за эту неделю"
        m = MONTHS_RU[self.month - 1].lower()
        return f"план на {m}" if self.kind == PLAN else f"факт за {m}"

    @property
    def what_en(self) -> str:
        if self.monday:
            return "weekly plan" if self.kind == PLAN else "weekly actuals"
        m = MONTHS_EN[self.month - 1]
        return f"{m} plan" if self.kind == PLAN else f"{m} actuals"


def period_for(role: str, kind: str, today: dt.date) -> Period:
    """Период, за который сотрудник сдаёт данные в этот день."""
    if role == KOMPLEKT:
        mon = week_monday(today)
        return Period(role, kind, f"W{mon.isoformat()}", mon.year, mon.month, mon)
    y, m = today.year, today.month
    # План, присланный в самом конце месяца, — уже на следующий месяц;
    # факт, присланный в первые дни, — ещё за прошлый.
    if kind == PLAN and today.day >= 25:
        y, m = _shift_month(y, m, 1)
    elif kind == FACT and today.day <= 5:
        y, m = _shift_month(y, m, -1)
    return Period(role, kind, f"M{y}-{m:02d}", y, m)


def period_from_key(role: str, kind: str, key: str) -> Period | None:
    try:
        if key.startswith("W"):
            mon = dt.date.fromisoformat(key[1:])
            return Period(role, kind, key, mon.year, mon.month, mon)
        if key.startswith("M"):
            y, m = (int(x) for x in key[1:].split("-"))
            return Period(role, kind, key, y, m)
    except ValueError:
        pass
    return None


def last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


@dataclass(frozen=True)
class Reminder:
    role: str
    kind: str
    first: bool  # True — первое напоминание, False — повторное (только не приславшим)
    at: dt.datetime


def reminders_on(day: dt.date) -> list[Reminder]:
    """Все напоминания, запланированные на этот день (дубайское время)."""
    def at(h: int) -> dt.datetime:
        return dt.datetime(day.year, day.month, day.day, h, 0, tzinfo=DUBAI)

    out: list[Reminder] = []
    if day.weekday() == 0:  # понедельник
        out += [Reminder(KOMPLEKT, PLAN, True, at(12)), Reminder(KOMPLEKT, PLAN, False, at(15))]
    if day.weekday() == 4:  # пятница
        out += [Reminder(KOMPLEKT, FACT, True, at(12)), Reminder(KOMPLEKT, FACT, False, at(15))]
    last = last_day(day.year, day.month)
    if day.day == 1:
        out.append(Reminder(PM, PLAN, True, at(12)))
    if day.day == 2:
        out.append(Reminder(PM, PLAN, False, at(12)))
    if day.day == last - 1:
        out.append(Reminder(PM, FACT, True, at(12)))
    if day.day == last:
        out.append(Reminder(PM, FACT, False, at(12)))
    return out


def reminder_text(r: Reminder, period: Period) -> str:
    if not r.first:
        return (
            f"⏰ Напоминание: {period.what_ru} от вас ещё не пришёл.\n\n"
            f"⏰ Reminder: we haven't received your {period.what_en} yet."
        )
    if r.role == KOMPLEKT:
        if r.kind == PLAN:
            ru = "📅 Пришлите, пожалуйста, план расходов на эту неделю — сегодня до 16:00."
            en = "📅 Please send your planned expenses for this week — today before 16:00."
        else:
            ru = "💰 Пришлите, пожалуйста, фактические расходы за эту неделю — сегодня до 16:00."
            en = "💰 Please send your actual expenses for this week — today before 16:00."
    else:
        m_ru = MONTHS_RU[period.month - 1].lower()
        m_en = MONTHS_EN[period.month - 1]
        if r.kind == PLAN:
            ru = f"📅 Пришлите, пожалуйста, план расходов на {m_ru}."
            en = f"📅 Please send your planned expenses for {m_en}."
        else:
            ru = f"💰 Пришлите, пожалуйста, фактические расходы за {m_ru}."
            en = f"💰 Please send your actual expenses for {m_en}."
    return (
        f"{ru}\n\nКаждый проект с новой строки, пример:\n"
        "381-03 Villa 29, Al Barsha — 12 500\n\n"
        f"{en}\nOne project per line, e.g.:\n"
        "381-03 Villa 29, Al Barsha — 12,500"
    )


# --- суммы и проекты -------------------------------------------------------

_THOUSANDS = {",": re.compile(r"^\d{1,3}(,\d{3})+$"), ".": re.compile(r"^\d{1,3}(\.\d{3})+$")}


def parse_amount(raw: str) -> float | None:
    """«12 500», «12,500», «97781,68», «53,264.42», «28,901.6» → число."""
    s = re.sub(r"(?i)aed|дирхам\w*|[\s  ']", "", str(raw or "")).strip()
    s = s.rstrip(".,")
    if not s or not re.fullmatch(r"\d[\d.,]*", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        if _THOUSANDS[sep].match(s):
            s = s.replace(sep, "")
        elif s.count(sep) == 1:
            s = s.replace(sep, ".")
        else:
            return None
    try:
        return float(s)
    except ValueError:
        return None


_CODE = re.compile(r"^\s*(\d{2,4})-(\d{1,3})\b(.*)$")


def project_error(project: str) -> str | None:
    """Проверка формата «381-03 Название»: код «номер-код» и название. None — всё хорошо."""
    m = _CODE.match(project or "")
    if not m:
        return "нет кода проекта (нужно, например, 381-03 и название)"
    name = m.group(3).strip(" ,.:;—–-")
    if not re.search(r"[A-Za-zА-Яа-яЁё]", name):
        return "после кода нужно название проекта"
    return None


_LINE = re.compile(
    r"^(?P<project>.+?)\s*(?:[—–:=]|\s-\s)\s*(?P<amount>\d[\d\s.,  ']*)"
    r"\s*(?:AED|aed|дирхам\w*)?\s*$"
)


def parse_simple(text: str) -> list[tuple[str, str]] | None:
    """Быстрый разбор без ИИ: каждая непустая строка «проект — сумма».

    Возвращает список (проект, сумма как написана) или None, если хоть одна
    строка не подходит (тогда текст разбирает Claude).
    """
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("•*-").strip()
        if not line:
            continue
        m = _LINE.match(line)
        if not m:
            return None
        out.append((m.group("project").strip(), m.group("amount").strip()))
    return out or None


def validate(items: list[dict]) -> tuple[list[tuple[str, float]], list[tuple[str, str]]]:
    """items: [{"project": str, "amounts": [str, ...]}].

    Возвращает (принятые [(проект, сумма)], ошибки [(строка, причина)]).
    """
    ok: list[tuple[str, float]] = []
    errors: list[tuple[str, str]] = []
    for it in items:
        project = str(it.get("project") or "").strip()
        amounts = [a for a in (it.get("amounts") or []) if str(a).strip()]
        shown = f"{project} — {', '.join(map(str, amounts))}" if amounts else project
        err = project_error(project)
        if err:
            errors.append((shown, err))
            continue
        if not amounts:
            errors.append((shown, "не нашёл сумму"))
            continue
        if len(amounts) > 1:
            errors.append((shown, "у проекта несколько сумм — оставьте одну"))
            continue
        value = parse_amount(str(amounts[0]))
        if value is None:
            errors.append((shown, "не понял сумму"))
            continue
        ok.append((project, value))
    return ok, errors


def fmt_amount(x: float) -> str:
    """12500 → «12 500», 97781.68 → «97 781,68»."""
    s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return s[:-3] if s.endswith(",00") else s


# --- хранилище: кто что прислал и какие напоминания уже ушли ----------------

STORE_FILE = pathlib.Path("data") / "expenses.json"


class ExpenseStore:
    def __init__(self, path: pathlib.Path = STORE_FILE) -> None:
        self.path = path
        self._data: dict = {"submissions": {}, "sent": {}}
        if path.exists():
            try:
                self._data.update(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                logging.warning("Не удалось прочитать %s — начинаю заново.", path)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            logging.exception("Не удалось сохранить %s", self.path)

    @staticmethod
    def _key(username: str, kind: str, period_key: str) -> str:
        return f"{username.lower()}|{kind}|{period_key}"

    def submission(self, username: str, kind: str, period_key: str) -> dict | None:
        return self._data["submissions"].get(self._key(username, kind, period_key))

    def record(self, username: str, kind: str, period_key: str, total: float) -> None:
        key = self._key(username, kind, period_key)
        entry = self._data["submissions"].setdefault(key, {"history": []})
        entry["history"].append(
            {"total": total, "at": now_dubai().isoformat(timespec="seconds")}
        )
        entry["total"] = total
        self._save()

    def was_sent(self, event_key: str) -> bool:
        return event_key in self._data["sent"]

    def mark_sent(self, event_key: str) -> None:
        self._data["sent"][event_key] = now_dubai().isoformat(timespec="seconds")
        # Не копим историю бесконечно — храним последние ~200 событий.
        if len(self._data["sent"]) > 200:
            for k in sorted(self._data["sent"], key=self._data["sent"].get)[:-200]:
                del self._data["sent"][k]
        self._save()
