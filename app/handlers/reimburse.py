"""Компенсация расходов: рассылка напоминаний с кнопками и сводка админу.

15 числа и в последний день месяца — 11:00, 15:00, 19:00 по Дубаю (максимум 3
сообщения). Кнопки: «Я передал(а)», «Расходов не было» — больше не пишем;
«Ещё не передал(а)» — напомним в следующий раз. В 22:00 — сводка админу.

Команды админа:
  /reimb_test   — тестовое напоминание только себе;
  /reimb_status — кто ответил за текущий период;
  /reimb_link <ID или @ник> <Имя из списка> — привязать человека без ника.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.notify import alert_admin
from app.reimburse import (
    ANSWER_TEXT,
    DONE,
    LATER,
    NONE,
    PEOPLE,
    ROUND_HOURS,
    SEND_WINDOW,
    SUMMARY_HOUR,
    Period,
    ReimburseStore,
    current_period,
    later_text,
    now_dubai,
    period_due_on,
    person,
    reminder_text,
)
from app.users import UserRegistry
from config import Config

router = Router()

CB = "rb"  # rb:<status>:<period key | TEST>
TEST_KEY = "TEST"

_store: ReimburseStore | None = None


def store() -> ReimburseStore:
    global _store
    if _store is None:
        _store = ReimburseStore()
    return _store


def _buttons(period_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я передал(а) / I've submitted", callback_data=f"{CB}:{DONE}:{period_key}")],
        [InlineKeyboardButton(text="🚫 Расходов не было / No expenses", callback_data=f"{CB}:{NONE}:{period_key}")],
        [InlineKeyboardButton(text="⏰ Ещё не передал(а) / Not yet", callback_data=f"{CB}:{LATER}:{period_key}")],
    ])


def resolve(p: dict, users: UserRegistry, st: ReimburseStore) -> int | None:
    """Telegram ID человека из списка: привязка админа, иначе по нику."""
    uid = st.linked_id(p["name"])
    if uid is None and p.get("username"):
        uid = users.find_by_username(p["username"])
    return uid


def _candidates(p: dict, users: UserRegistry, taken: set[int]) -> list[tuple[int, str, str]]:
    """Пользователи бота, похожие по имени на человека без привязки (подсказка админу)."""
    out = []
    for uid, name, username in users.entries():
        if uid in taken:
            continue
        hay = f"{name} {username}".lower()
        if any(a in hay for a in p.get("aliases", [])):
            out.append((uid, name, username))
    return out


def _who(uid: int, users: UserRegistry) -> str:
    for i, name, username in users.entries():
        if i == uid:
            return f"{html.escape(name)}" + (f" (@{username})" if username else "")
    return str(uid)


def build_status(period: Period, users: UserRegistry, st: ReimburseStore) -> str:
    groups: dict[str, list[str]] = {DONE: [], NONE: [], LATER: [], "silent": [], "off": []}
    resolved = {p["name"]: resolve(p, users, st) for p in PEOPLE}
    taken = {u for u in resolved.values() if u}
    for p in PEOPLE:
        uid = resolved[p["name"]]
        name = html.escape(p["name"])
        if uid is None:
            hint = ""
            cands = _candidates(p, users, taken)
            if cands:
                hint = "\n   возможно: " + "; ".join(
                    f"<code>/reimb_link {u} {name}</code> — {html.escape(n)}" + (f" @{un}" if un else "")
                    for u, n, un in cands
                )
            groups["off"].append(f"• {name}" + (f" (@{p['username']})" if p.get("username") else "") + hint)
            continue
        a = st.answer(period.key, uid)
        status = a["status"] if a else "silent"
        when = f" — {a['at'][11:16]}" if a else ""
        groups[status].append(f"• {name}{when}")
    titles = [
        (DONE, "✅ Передали"),
        (NONE, "🚫 Расходов не было"),
        (LATER, "⏰ Нажали «Ещё не передал(а)»"),
        ("silent", "😶 Не ответили"),
        ("off", "❌ Не подключены к боту (не нажали /start)"),
    ]
    lines = [f"💸 <b>Компенсация расходов за {period.label_ru}</b>", ""]
    for key, title in titles:
        if groups[key]:
            lines.append(f"<b>{title}</b> ({len(groups[key])})")
            lines.extend(groups[key])
            lines.append("")
    return "\n".join(lines).strip()


# --- кнопки ------------------------------------------------------------------

@router.callback_query(F.data.startswith(f"{CB}:"))
async def on_button(callback: CallbackQuery, config: Config) -> None:
    try:
        _, status, key = callback.data.split(":", 2)
    except ValueError:
        await callback.answer()
        return
    now = now_dubai()
    if key == TEST_KEY:
        period = period_due_on(now.date()) or current_period(now.date())
    else:
        period = Period.from_key(key)
        if period is None or status not in (DONE, NONE, LATER):
            await callback.answer()
            return
        # «Ещё не передал» не перезаписывает уже данный окончательный ответ.
        if status == LATER and store().is_final(key, callback.from_user.id):
            status = store().answer(key, callback.from_user.id)["status"]
        else:
            store().set_answer(key, callback.from_user.id, status)
    await callback.answer()
    reply = ANSWER_TEXT.get(status) or later_text(now, period)
    if key == TEST_KEY:
        reply = "🧪 ТЕСТ (ничего не записано)\n\n" + reply
    if status in (DONE, NONE):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001 — сообщение уже без кнопок
            pass
    await callback.message.answer(reply)


# --- команды администратора --------------------------------------------------

@router.message(Command("reimb_test"))
async def reimb_test(message: Message, config: Config) -> None:
    if not config.is_admin(message.from_user.id):
        return
    today = now_dubai().date()
    period = period_due_on(today) or current_period(today)
    await message.answer(reminder_text(period, 1, test=True), reply_markup=_buttons(TEST_KEY))


@router.message(Command("reimb_status"))
async def reimb_status(message: Message, config: Config, users: UserRegistry) -> None:
    if not config.is_admin(message.from_user.id):
        return
    period = current_period(now_dubai().date())
    await message.answer(build_status(period, users, store()))


@router.message(Command("reimb_link"))
async def reimb_link(message: Message, command: CommandObject, config: Config, users: UserRegistry) -> None:
    if not config.is_admin(message.from_user.id):
        return
    usage = (
        "Формат: <code>/reimb_link 123456789 Имя</code> или <code>/reimb_link @ник Имя</code>\n"
        "Имя — как в списке: " + ", ".join(p["name"] for p in PEOPLE)
    )
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(usage)
        return
    who, name = parts
    p = person(name)
    if p is None:
        await message.answer(f"Не нашёл «{html.escape(name)}» в списке.\n\n{usage}")
        return
    uid = users.find_by_username(who) if who.startswith("@") else (int(who) if who.isdigit() else None)
    if uid is None:
        await message.answer(
            f"Не нашёл пользователя {html.escape(who)} среди пользователей бота — "
            "пусть человек сначала нажмёт /start. Все ID: /users"
        )
        return
    store().link(p["name"], uid)
    await message.answer(f"✅ {html.escape(p['name'])} привязан(а): {_who(uid, users)}")


# --- расписание --------------------------------------------------------------

async def _send_round(bot, config: Config, users: UserRegistry, period: Period, round_no: int) -> None:
    st = store()
    text = reminder_text(period, round_no)
    unreachable: list[str] = []
    sent = 0
    for p in PEOPLE:
        uid = resolve(p, users, st)
        if uid is None:
            unreachable.append(p["name"])
            continue
        if st.is_final(period.key, uid):
            continue
        try:
            await bot.send_message(uid, text, reply_markup=_buttons(period.key))
            sent += 1
        except TelegramForbiddenError:
            unreachable.append(p["name"])
        except Exception:  # noqa: BLE001
            logging.exception("Компенсация: не удалось отправить напоминание %s", p["name"])
        await asyncio.sleep(0.1)
    logging.info("Компенсация %s: раунд %d, отправлено %d", period.key, round_no, sent)
    if unreachable and round_no == 1:
        await alert_admin(
            bot, config,
            "⚠️ Компенсация расходов: не смог отправить напоминание — эти сотрудники "
            "не нажали /start в боте (или заблокировали его):\n"
            + "\n".join(f"• {html.escape(n)}" for n in unreachable)
            + "\n\nПодробнее и подсказки для привязки: /reimb_status",
        )


async def _tick(bot, config: Config, users: UserRegistry) -> None:
    now = now_dubai()
    period = period_due_on(now.date())
    if period is None:
        return
    st = store()
    for i, hour in enumerate(ROUND_HOURS, start=1):
        at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        event = f"{period.key}|round{i}"
        if at <= now < at + SEND_WINDOW and not st.was_sent(event):
            st.mark_sent(event)
            await _send_round(bot, config, users, period, i)
    at = now.replace(hour=SUMMARY_HOUR, minute=0, second=0, microsecond=0)
    event = f"{period.key}|summary"
    if now >= at and not st.was_sent(event):
        st.mark_sent(event)
        await alert_admin(bot, config, build_status(period, users, st))


async def reminders_loop(bot, config: Config, users: UserRegistry) -> None:
    """Каждые 30 секунд проверяет, не пора ли отправить напоминание."""
    while True:
        try:
            await _tick(bot, config, users)
        except Exception:  # noqa: BLE001
            logging.exception("Компенсация: ошибка в расписании напоминаний")
        await asyncio.sleep(30)
