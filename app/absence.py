"""«🏖 Отсутствие»: период отсутствия сотрудника — проверка, текст, хранилище.

Даты из свободного текста («со вторника по четверг», «завтра с 10 до 13»)
разбирает Claude (app/claude_answer.py → parse_absence); здесь — проверка того,
что он вернул, и человеческий текст периода на русском и английском.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib
import re
from dataclasses import asdict, dataclass

from app.expenses import now_dubai

STORE_FILE = pathlib.Path("data") / "absences.json"

WD_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WD_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PART_RU = {"first_half": "первую половину дня", "second_half": "вторую половину дня"}
PART_EN = {"first_half": "the first half of the day", "second_half": "the second half of the day"}

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class Period:
    start: dt.date
    end: dt.date
    start_time: str | None = None  # «10:00» — только для одного дня
    end_time: str | None = None
    part: str | None = None  # first_half / second_half

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def partial(self) -> bool:
        return bool(self.start_time or self.end_time or self.part)


def _date(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def _time(v) -> str | None:
    if not v:
        return None
    m = _TIME.match(str(v).strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def check_parsed(data: dict, today: dt.date) -> tuple[Period | None, str | None]:
    """Ответ Claude → (период, None) или (None, уточняющий вопрос)."""
    if data.get("status") != "ok":
        return None, data.get("question") or ""
    start = _date(data.get("start_date"))
    end = _date(data.get("end_date")) or start
    if start is None:
        return None, data.get("question") or ""
    if end < start:
        start, end = end, start
    if end < today:
        return None, "past"
    if (end - start).days > 120:
        return None, "too_long"
    p = Period(start, end, _time(data.get("start_time")), _time(data.get("end_time")),
               data.get("part") if data.get("part") in PART_RU else None)
    if p.days > 1:  # часы и половина дня — только для одного дня
        p.start_time = p.end_time = p.part = None
    return p, None


def _d(d: dt.date, lang: str) -> str:
    wd = (WD_EN if lang == "en" else WD_RU)[d.weekday()]
    return f"{wd} {d:%d.%m}"


def period_text(p: Period, lang: str) -> str:
    """«с пн 16.11 по ср 18.11 (3 дня)», «в пт 13.11 с 10:00 до 13:00»."""
    if lang == "en":
        if p.days > 1:
            return f"from {_d(p.start, 'en')} to {_d(p.end, 'en')} ({p.days} days)"
        s = f"on {_d(p.start, 'en')}"
        if p.part:
            return f"{s}, {PART_EN[p.part]}"
        if p.start_time and p.end_time:
            return f"{s} from {p.start_time} to {p.end_time}"
        if p.start_time:
            return f"{s} from {p.start_time}"
        if p.end_time:
            return f"{s} until {p.end_time}"
        return f"{s} (all day)"
    if p.days > 1:
        return f"с {_d(p.start, 'ru')} по {_d(p.end, 'ru')} ({_days_ru(p.days)})"
    s = f"в {_d(p.start, 'ru')}"
    if p.part:
        return f"{s}, {PART_RU[p.part]}"
    if p.start_time and p.end_time:
        return f"{s} с {p.start_time} до {p.end_time}"
    if p.start_time:
        return f"{s} с {p.start_time}"
    if p.end_time:
        return f"{s} до {p.end_time}"
    return f"{s} (весь день)"


def _days_ru(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"


def team_message(who: str, p: Period, test: bool = False) -> str:
    """Рассылка команде — на русском и английском."""
    head = "🧪 <b>ТЕСТ / TEST</b> — это проверка, не настоящее отсутствие\n\n" if test else ""
    return (
        f"{head}🏖 <b>Отсутствие сотрудника</b>\n"
        f"{who} будет отсутствовать {period_text(p, 'ru')} и будет не на связи.\n\n"
        f"🏖 <b>Team member away</b>\n"
        f"{who} will be away {period_text(p, 'en')} and unavailable."
    )


def record(user_id: int, who: str, p: Period, text: str, test: bool, delivered: int) -> None:
    """Запоминает отсутствие в data/absences.json (история для руководителей)."""
    try:
        items = json.loads(STORE_FILE.read_text(encoding="utf-8")) if STORE_FILE.exists() else []
    except (json.JSONDecodeError, OSError):
        items = []
    entry = asdict(p)
    entry.update(
        start=p.start.isoformat(), end=p.end.isoformat(), user_id=user_id, who=who,
        text=text, test=test, delivered=delivered,
        created=now_dubai().isoformat(timespec="seconds"),
    )
    items.append(entry)
    try:
        STORE_FILE.parent.mkdir(exist_ok=True)
        STORE_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logging.exception("Не удалось сохранить %s", STORE_FILE)
