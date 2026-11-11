"""«🏖 Отсутствие» — сотрудник сообщает, когда его не будет, бот уведомляет команду.

Поток: кнопка → «Когда вас не будет?» (свободный текст или голосовое) → Claude
разбирает даты/время (непонятно — бот переспрашивает) → «Вас не будет … Всё верно?»
[✅ Подтвердить] [✏️ Изменить] → запись в data/absences.json + рассылка всем, кто
запускал бота (RU + EN).

Тест: /absence_test (админ) — тот же путь, но уведомление с пометкой «ТЕСТ»
приходит только админу, команде ничего не уходит.
"""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import absence as ab
from app import keyboards as kb
from app.claude_answer import describe_error
from app.expenses import now_dubai
from app.i18n import t
from app.knowledge_service import KnowledgeService
from app.notify import alert_admin
from app.transcribe import Transcriber, voice_to_text
from app.users import UserRegistry
from config import Config

router = Router()

CB_OK = "abs_ok"
CB_EDIT = "abs_edit"
MAX_ROUNDS = 3  # сколько раз переспрашиваем, прежде чем попросить точные даты

TXT = {
    "ask": {
        "ru": (
            "🏖 <b>Отсутствие</b>\n\n"
            "Когда вас не будет? Напишите как удобно — текстом или голосовым. Например:\n"
            "• «с 16 по 20 ноября»\n"
            "• «со вторника по четверг»\n"
            "• «завтра с 10 до 13»\n"
            "• «в пятницу первую половину дня»"
        ),
        "en": (
            "🏖 <b>Time off</b>\n\n"
            "When will you be away? Write it any way you like — by text or voice. E.g.:\n"
            "• «from 16 to 20 November»\n"
            "• «Tuesday to Thursday»\n"
            "• «tomorrow from 10 to 13»\n"
            "• «Friday, first half of the day»"
        ),
    },
    "test": {
        "ru": "🧪 <b>Тестовый режим</b>: уведомление придёт только вам, команде ничего не уйдёт.\n\n",
        "en": "🧪 <b>Test mode</b>: the notification goes only to you, not to the team.\n\n",
    },
    "thinking": {"ru": "⏳ Разбираю даты…", "en": "⏳ Reading the dates…"},
    "confirm": {
        "ru": "Проверьте: вас не будет <b>{period}</b>.\n\nВсё верно? После подтверждения команда получит уведомление.",
        "en": "Please check: you will be away <b>{period}</b>.\n\nIs that right? Once confirmed, the team will be notified.",
    },
    "unclear": {"ru": "🤔 {q}", "en": "🤔 {q}"},
    "unclear_default": {
        "ru": "Не до конца понял даты. Уточните, пожалуйста: с какого и по какое число вас не будет (и время, если это часть дня)?",
        "en": "I didn't quite get the dates. Could you specify from which date to which you'll be away (and the time, if it's part of a day)?",
    },
    "exact": {
        "ru": "Напишите, пожалуйста, точные даты, например: «с 16.11 по 18.11» или «13.11 с 10:00 до 13:00».",
        "en": "Please write exact dates, e.g. «16.11–18.11» or «13.11 from 10:00 to 13:00».",
    },
    "past": {
        "ru": "Похоже, эти даты уже прошли. Напишите, пожалуйста, когда вас не будет — сегодня или позже.",
        "en": "Those dates seem to be in the past. Please write when you'll be away — today or later.",
    },
    "too_long": {
        "ru": "Период получился больше 4 месяцев — уточните, пожалуйста, даты.",
        "en": "The period is over 4 months — please check the dates.",
    },
    "fail": {
        "ru": "😕 Не получилось разобрать сообщение. Напишите даты, например: «с 16.11 по 18.11».",
        "en": "😕 Couldn't read the message. Please write the dates, e.g. «16.11–18.11».",
    },
    "need_text": {"ru": "Напишите текстом или отправьте голосовое (или нажмите «Отмена»).",
                  "en": "Please send text or a voice message (or press «Cancel»)."},
    "sending": {"ru": "📨 Уведомляю команду…", "en": "📨 Notifying the team…"},
    "done": {
        "ru": "✅ Готово! Отсутствие зафиксировано, команда уведомлена ({n} чел.).",
        "en": "✅ Done! Your time off is recorded and the team has been notified ({n} people).",
    },
    "done_test": {
        "ru": "✅ Тест завершён: уведомление выше пришло только вам. Команде ничего не отправлено.",
        "en": "✅ Test complete: the notification above went only to you. Nothing was sent to the team.",
    },
}


def _tx(key: str, lang: str, **kw) -> str:
    return TXT[key]["en" if lang == "en" else "ru"].format(**kw)


class AbsenceStates(StatesGroup):
    waiting = State()
    confirming = State()


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить / Confirm", callback_data=CB_OK),
        InlineKeyboardButton(text="✏️ Изменить / Edit", callback_data=CB_EDIT),
    ]])


def _who(user) -> str:
    """Имя для рассылки: «Иван Огиенко (@ivan_ogienko)»."""
    name = html.escape(user.full_name or "Сотрудник")
    return f"<b>{name}</b>" + (f" (@{html.escape(user.username)})" if user.username else "")


async def _start(message: Message, state: FSMContext, lang: str, test: bool) -> None:
    await state.clear()
    await state.set_state(AbsenceStates.waiting)
    await state.update_data(test=test, history=[], rounds=0)
    text = (_tx("test", lang) if test else "") + _tx("ask", lang)
    await message.answer(text, reply_markup=kb.cancel_menu("с 16 по 20 ноября / Tue–Thu"))


@router.message(F.text == kb.BTN_ABSENCE)
async def enter(message: Message, state: FSMContext, users: UserRegistry) -> None:
    await _start(message, state, users.get_lang(message.from_user.id), test=False)


@router.message(Command("absence_test"))
async def enter_test(message: Message, state: FSMContext, config: Config, users: UserRegistry) -> None:
    """Админ: пройти весь путь, но уведомление с «ТЕСТ» получает только админ."""
    if not config.is_admin(message.from_user.id):
        return
    await _start(message, state, users.get_lang(message.from_user.id), test=True)


@router.message(AbsenceStates.waiting, F.text == kb.BTN_CANCEL)
@router.message(AbsenceStates.confirming, F.text == kb.BTN_CANCEL)
async def cancel(message: Message, state: FSMContext, config: Config, users: UserRegistry) -> None:
    await state.clear()
    await message.answer(
        t("cancelled", users.get_lang(message.from_user.id)),
        reply_markup=kb.main_menu(config.is_admin(message.from_user.id)),
    )


@router.message(AbsenceStates.waiting, F.text | F.voice)
@router.message(AbsenceStates.confirming, F.text | F.voice)
async def receive(
    message: Message,
    state: FSMContext,
    config: Config,
    users: UserRegistry,
    knowledge: KnowledgeService,
    transcriber: Transcriber,
) -> None:
    if message.text and message.text in kb.MAIN_BUTTONS:
        await state.clear()
        raise SkipHandler  # нажата другая кнопка меню — пусть её обработает свой раздел
    lang = users.get_lang(message.from_user.id)
    if knowledge.answerer is None:
        await message.answer(_tx("fail", lang))
        return

    text = message.text or ""
    if message.voice:
        await message.answer(_tx("thinking", lang))
        try:
            text, _ = await voice_to_text(message.bot, message.voice, transcriber)
        except Exception:  # noqa: BLE001
            logging.exception("Отсутствие: не удалось распознать голосовое")
            text = ""
        if not text:
            await message.answer(_tx("need_text", lang))
            return

    data = await state.get_data()
    history: list[str] = list(data.get("history", []))
    history.append(text)
    rounds = int(data.get("rounds", 0)) + 1
    # Уточнения копим: «на неделе» + «со вторника» — вместе дают ответ.
    combined = "\n".join(f"— {h}" for h in history[-4:])

    today = now_dubai().date()
    try:
        parsed = await knowledge.answerer.parse_absence(combined, today)
    except Exception as err:  # noqa: BLE001
        logging.exception("Отсутствие: Claude не смог разобрать даты")
        await alert_admin(
            message.bot, config,
            f"⚠️ «Отсутствие»: Claude не разобрал даты.\nПричина: {html.escape(describe_error(err))}",
        )
        await message.answer(_tx("fail", lang))
        return

    period, question = ab.check_parsed(parsed, today)
    await state.update_data(history=history, rounds=rounds, source=text)
    if period is None:
        await state.set_state(AbsenceStates.waiting)
        if question in ("past", "too_long"):
            await state.update_data(history=[])
            await message.answer(_tx(question, lang))
        elif rounds >= MAX_ROUNDS:
            await state.update_data(history=[], rounds=0)
            await message.answer(_tx("exact", lang))
        else:
            await message.answer(_tx("unclear", lang, q=html.escape(question)) if question
                                 else _tx("unclear_default", lang))
        return

    await state.update_data(period={
        "start": period.start.isoformat(), "end": period.end.isoformat(),
        "start_time": period.start_time, "end_time": period.end_time, "part": period.part,
    })
    await state.set_state(AbsenceStates.confirming)
    await message.answer(
        _tx("confirm", lang, period=ab.period_text(period, lang)), reply_markup=_confirm_kb()
    )


@router.message(AbsenceStates.waiting)
async def not_text(message: Message, users: UserRegistry) -> None:
    await message.answer(_tx("need_text", users.get_lang(message.from_user.id)))


@router.callback_query(AbsenceStates.confirming, F.data == CB_EDIT)
async def edit(callback: CallbackQuery, state: FSMContext, users: UserRegistry) -> None:
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    await _start(callback.message, state, users.get_lang(callback.from_user.id), data.get("test", False))


@router.callback_query(AbsenceStates.confirming, F.data == CB_OK)
async def confirm(
    callback: CallbackQuery, state: FSMContext, config: Config, users: UserRegistry
) -> None:
    await callback.answer()
    lang = users.get_lang(callback.from_user.id)
    is_admin = config.is_admin(callback.from_user.id)
    data = await state.get_data()
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    raw = data["period"]
    period = ab.Period(
        start=ab.dt.date.fromisoformat(raw["start"]), end=ab.dt.date.fromisoformat(raw["end"]),
        start_time=raw["start_time"], end_time=raw["end_time"], part=raw["part"],
    )
    test = bool(data.get("test")) and is_admin
    user = callback.from_user
    text = ab.team_message(_who(user), period, test=test)

    if test:
        recipients = [user.id]
    else:
        recipients = [uid for uid in users.all_ids() if uid != user.id]
        await callback.message.answer(_tx("sending", lang))
    delivered = await _broadcast(callback.bot, recipients, text)
    ab.record(user.id, user.full_name or "", period, data.get("source", ""), test, delivered)
    await callback.message.answer(
        _tx("done_test", lang) if test else _tx("done", lang, n=delivered),
        reply_markup=kb.main_menu(is_admin),
    )


async def _broadcast(bot, ids: list[int], text: str) -> int:
    """Отправка с паузой (лимиты Telegram); возвращает, скольким доставлено."""
    delivered = 0
    for uid in ids:
        try:
            await bot.send_message(uid, text)
            delivered += 1
        except TelegramForbiddenError:
            pass  # человек заблокировал бота
        except TelegramRetryAfter as err:
            await asyncio.sleep(err.retry_after)
            try:
                await bot.send_message(uid, text)
                delivered += 1
            except Exception:  # noqa: BLE001
                logging.warning("Отсутствие: не доставлено %s", uid)
        except Exception:  # noqa: BLE001
            logging.exception("Отсутствие: ошибка отправки %s", uid)
        await asyncio.sleep(0.05)
    return delivered
