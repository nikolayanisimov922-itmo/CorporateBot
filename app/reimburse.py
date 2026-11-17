"""Компенсация расходов (такси и пр.): напоминания сдать отчёт финансисту.

Дважды в месяц — 15 числа (за 1–15) и в последний день месяца (за 16–конец) —
бот пишет сотрудникам из списка PEOPLE в личку. Максимум 3 сообщения в этот
день: 11:00, 15:00, 19:00 по Дубаю. Кто нажал «Я передал» или «Расходов не
было» — больше не получает. Сами расходы и чеки бот не принимает: люди сдают
их в чат расходов, как раньше.

Хранилище data/reimburse.json: привязки людей без ника, ответы по периодам,
какие рассылки уже ушли (чтобы после перезапуска не дублировать).
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import pathlib
from dataclasses import dataclass

from app.expenses import MONTHS_EN, now_dubai

# Кому напоминать. username — ник в Telegram без @, id — Telegram ID (если известен;
# надёжнее ника). Без того и другого — привязка админом через /reimb_link.
# aliases — как имя может быть написано в Telegram (для подсказок админу).
PEOPLE: list[dict] = [
    {"name": "Полина", "username": "oohgirllookathim", "aliases": ["polina", "poly", "полина"]},
    {"name": "Илья", "username": "dizworldwide", "aliases": ["ilya", "ilia", "илья"]},
    {"name": "Владимир", "username": "Vladimir_Belkanov", "aliases": ["vladimir", "владимир"]},
    {"name": "Татьяна", "username": "tetiana_bachynska", "aliases": ["tetiana", "tatiana", "татьяна"]},
    {"name": "Файза", "username": "Faiza_1999", "id": 5433631411, "aliases": ["faiza", "fayza", "faizah", "файза"]},
    {"name": "Алена", "username": "alenka_lykova", "aliases": ["alena", "алена", "алёна"]},
    {"name": "Мэй", "username": "May_Magdy", "aliases": ["may", "мэй"]},
    {"name": "Омар", "username": "Oalrawii", "id": 7744946171, "aliases": ["omar", "омар"]},
    {"name": "Мохаммед", "username": "mhmd_baroudi", "id": 6370846393, "aliases": ["moham", "muham", "mohd", "мохам", "мухам", "мохаммед"]},
    {"name": "Ансия", "username": "amiii1234", "aliases": ["ansiya", "ansia", "ансия"]},
    {"name": "Алина", "username": "sova_designed", "aliases": ["alina", "алина"]},
    {"name": "Сана", "username": "Sanii_999", "id": 6274397777, "aliases": ["sana", "сана"]},
    {"name": "Мерим", "username": "merimka9303", "aliases": ["meerim", "merim", "мерим", "меерим"]},
]

# Время напоминаний (час по Дубаю). Номер раунда = индекс + 1.
ROUND_HOURS = (11, 15, 19)
SUMMARY_HOUR = 22  # сводка админу в день сдачи
SEND_WINDOW = dt.timedelta(hours=2)  # бот был выключен дольше — раунд пропускаем

DONE = "done"
NONE = "none"
LATER = "later"
FINAL = (DONE, NONE)

MONTHS_RU_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def person(name: str) -> dict | None:
    n = name.strip().lower()
    for p in PEOPLE:
        if p["name"].lower() == n:
            return p
    return None


# --- периоды -----------------------------------------------------------------

@dataclass(frozen=True)
class Period:
    year: int
    month: int
    half: int  # 1 — с 1 по 15, 2 — с 16 по конец месяца

    @property
    def key(self) -> str:
        return f"{self.year}-{self.month:02d}-H{self.half}"

    @property
    def first_day(self) -> int:
        return 1 if self.half == 1 else 16

    @property
    def last_day(self) -> int:
        return 15 if self.half == 1 else calendar.monthrange(self.year, self.month)[1]

    @property
    def due(self) -> dt.date:
        """День сдачи (и рассылки)."""
        return dt.date(self.year, self.month, self.last_day)

    @property
    def label_ru(self) -> str:
        return f"{self.first_day}–{self.last_day} {MONTHS_RU_GEN[self.month - 1]}"

    @property
    def label_en(self) -> str:
        return f"{MONTHS_EN[self.month - 1]} {self.first_day}–{self.last_day}"

    @classmethod
    def from_key(cls, key: str) -> Period | None:
        try:
            y, m, h = key.split("-")
            p = cls(int(y), int(m), int(h.lstrip("H")))
            return p if p.half in (1, 2) and 1 <= p.month <= 12 else None
        except ValueError:
            return None


def period_due_on(day: dt.date) -> Period | None:
    """Период, который сдаётся в этот день (15 число или последний день месяца)."""
    if day.day == 15:
        return Period(day.year, day.month, 1)
    if day.day == calendar.monthrange(day.year, day.month)[1]:
        return Period(day.year, day.month, 2)
    return None


def current_period(day: dt.date) -> Period:
    """Ближайший период «на сегодня»: идущий или только что сданный (для /reimb_status)."""
    if day.day <= 15:
        if day.day == 15:
            return Period(day.year, day.month, 1)
        # 1–14 число: показываем прошлый период (вторая половина прошлого месяца).
        prev = day.replace(day=1) - dt.timedelta(days=1)
        return Period(prev.year, prev.month, 2)
    last = calendar.monthrange(day.year, day.month)[1]
    return Period(day.year, day.month, 2) if day.day == last else Period(day.year, day.month, 1)


# --- тексты ------------------------------------------------------------------

def reminder_text(period: Period, round_no: int, test: bool = False) -> str:
    """Текст напоминания RU + EN (HTML)."""
    head = "🧪 <b>ТЕСТ</b> — так сообщение увидят сотрудники.\n\n" if test else ""
    if round_no > 1:
        head += f"🔔 Повторное напоминание ({round_no}/{len(ROUND_HOURS)}) / Reminder ({round_no}/{len(ROUND_HOURS)})\n\n"
    return (
        head
        + "Здравствуйте!\n"
        f"Напоминаем, что до конца сегодняшнего дня вам нужно <b>ОБЯЗАТЕЛЬНО</b> "
        f"передать расходы за <b>{period.label_ru}</b>, чтобы получить за них компенсацию.\n"
        "Пожалуйста, передайте эту информацию в чат расходов.\n\n"
        "Hello!\n"
        f"This is a reminder that by the end of today you <b>MUST</b> submit your "
        f"expenses for <b>{period.label_en}</b> to receive reimbursement.\n"
        "Please send this information to the expenses chat."
    )


ANSWER_TEXT = {
    DONE: "✅ Спасибо! Отмечено: расходы переданы.\n✅ Thank you! Marked as submitted.",
    NONE: "✅ Спасибо! Отмечено: расходов не было.\n✅ Thank you! Marked as no expenses.",
}


def later_text(now: dt.datetime, period: Period) -> str:
    nxt = next_round_time(now, period)
    if nxt is None:
        return (
            "⏰ Пожалуйста, не забудьте передать расходы сегодня.\n"
            "⏰ Please don't forget to submit your expenses today."
        )
    return (
        f"⏰ Хорошо, напомню в {nxt:%H:%M}.\n"
        f"⏰ OK, I'll remind you at {nxt:%H:%M} (Dubai time)."
    )


def next_round_time(now: dt.datetime, period: Period) -> dt.datetime | None:
    if now.date() != period.due:
        return None
    for h in ROUND_HOURS:
        at = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if at > now:
            return at
    return None


# --- хранилище ---------------------------------------------------------------

STORE_FILE = pathlib.Path("data") / "reimburse.json"


class ReimburseStore:
    def __init__(self, path: pathlib.Path = STORE_FILE) -> None:
        self.path = path
        self._data: dict = {"links": {}, "answers": {}, "sent": {}}
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

    # привязки «имя из списка → Telegram ID» (для тех, у кого нет ника)
    def link(self, name: str, user_id: int) -> None:
        self._data["links"][name] = user_id
        self._save()

    def linked_id(self, name: str) -> int | None:
        v = self._data["links"].get(name)
        return int(v) if v else None

    # ответы сотрудников
    def answer(self, period_key: str, user_id: int) -> dict | None:
        return self._data["answers"].get(period_key, {}).get(str(user_id))

    def set_answer(self, period_key: str, user_id: int, status: str) -> None:
        self._data["answers"].setdefault(period_key, {})[str(user_id)] = {
            "status": status,
            "at": now_dubai().isoformat(timespec="seconds"),
        }
        # Храним ответы только за последние 12 периодов.
        keys = sorted(self._data["answers"])
        for k in keys[:-12]:
            del self._data["answers"][k]
        self._save()

    def is_final(self, period_key: str, user_id: int) -> bool:
        a = self.answer(period_key, user_id)
        return bool(a and a.get("status") in FINAL)

    # отправленные рассылки
    def was_sent(self, event_key: str) -> bool:
        return event_key in self._data["sent"]

    def mark_sent(self, event_key: str) -> None:
        self._data["sent"][event_key] = now_dubai().isoformat(timespec="seconds")
        if len(self._data["sent"]) > 100:
            for k in sorted(self._data["sent"], key=self._data["sent"].get)[:-100]:
                del self._data["sent"][k]
        self._save()
