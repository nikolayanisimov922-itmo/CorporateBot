"""План/факт расходов: напоминания по расписанию и приём данных.

Поток: напоминание с кнопкой (или «📤 Передать данные» в меню) → сотрудник
присылает список «381-03 Название — сумма» → бот проверяет формат (номер
вида 381-03 и название обязательны) → показывает, как понял, → «✅ Верно» →
запись в Google-таблицу. Повторные напоминания получают только не приславшие.

Администратор (не из команды) может пройти весь путь в тестовом режиме —
данные пишутся на отдельный лист «Тест». Команды админа: /team, /exp_test.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app import keyboards as kb
from app.claude_answer import describe_error
from app.expenses import (
    FACT,
    FORMAT_EXAMPLE,
    KIND_RU,
    KOMPLEKT,
    PLAN,
    PM,
    ExpenseStore,
    Period,
    Reminder,
    fmt_amount,
    member_by_username,
    members,
    now_dubai,
    parse_simple,
    period_for,
    period_from_key,
    reminder_text,
    reminders_on,
    validate,
)
from app.expenses_sheet import TEST_WORKSHEET, ensure_current_month, write_submission
from app.i18n import t
from app.knowledge_service import KnowledgeService
from app.notify import alert_admin
from app.sheets import SheetsClient
from app.users import UserRegistry
from config import Config

router = Router()

CB_START = "exp"  # exp:<kind>:<period key>
CB_OK = "exp_ok"
CB_REDO = "exp_redo"
BTN_SUBMIT = "📤 Передать данные / Submit data"

KIND_BUTTONS = {
    (KOMPLEKT, PLAN): "📅 План на неделю / Weekly plan",
    (KOMPLEKT, FACT): "💰 Факт за неделю / Weekly actuals",
    (PM, PLAN): "📅 План на месяц / Monthly plan",
    (PM, FACT): "💰 Факт за месяц / Monthly actuals",
}
ICON = {PLAN: "📅", FACT: "💰"}

TXT = {
    "ask": {
        "ru": (
            "{icon} <b>{kind} · {period}</b>\n\n"
            "Пришлите одним сообщением список проектов — каждый с новой строки: "
            "код проекта (например, 381-03), название и сумма.\n\nПример:\n{example}"
        ),
        "en": (
            "{icon} <b>{kind_en} · {period}</b>\n\n"
            "Send the list of projects in one message — one per line: "
            "project code (e.g. 381-03), name and amount.\n\nExample:\n{example}"
        ),
    },
    "bad_format": {
        "ru": (
            "❌ Не могу принять — проверьте эти строки:\n{lines}\n\n"
            "Каждый проект: код (например, 381-03) и название, затем сумма. Пример:\n{example}\n\n"
            "Пришлите список заново целиком."
        ),
        "en": (
            "❌ Can't accept it — please check these lines:\n{lines}\n\n"
            "Each project: code (e.g. 381-03) and name, then the amount. Example:\n{example}\n\n"
            "Please send the whole list again."
        ),
    },
    "nothing": {
        "ru": "Не нашёл в сообщении ни одного проекта с суммой. Пример:\n{example}",
        "en": "I couldn't find any project with an amount. Example:\n{example}",
    },
    "parse_fail": {
        "ru": (
            "😕 Не получилось разобрать сообщение. Пришлите, пожалуйста, каждый "
            "проект отдельной строкой в формате:\n{example}"
        ),
        "en": (
            "😕 I couldn't read the message. Please send each project on its own "
            "line like this:\n{example}"
        ),
    },
    "confirm": {
        "ru": "{icon} <b>{kind} · {period}</b>\n\n{lines}\n\n<b>Итого: {total} AED</b>{again}\n\nВсё верно?",
        "en": "{icon} <b>{kind_en} · {period}</b>\n\n{lines}\n\n<b>Total: {total} AED</b>{again}\n\nIs everything correct?",
    },
    "again": {
        "ru": "\n\n⚠️ Вы уже присылали данные за этот период ({prev} AED). Новая сумма заменит прежнюю в сводке, прежняя сохранится в деталях.",
        "en": "\n\n⚠️ You already sent data for this period ({prev} AED). The new total will replace it in the summary; the old one stays in the details.",
    },
    "saved": {"ru": "✅ Принято, спасибо!", "en": "✅ Received, thank you!"},
    "saved_backup": {
        "ru": "✅ Принято, спасибо! (Таблица временно недоступна — данные переданы администратору.)",
        "en": "✅ Received, thank you! (The table is temporarily unavailable — the data was passed to the administrator.)",
    },
    "need_text": {
        "ru": "Пришлите список текстом (или нажмите «Отмена»).",
        "en": "Please send the list as text (or press «Cancel»).",
    },
    "not_member": {
        "ru": (
            "Передача плана и факта расходов — для комплектаторов и проджект-"
            "менеджеров. Если вы из этих отделов, напишите администратору."
        ),
        "en": (
            "Plan/actual expenses are submitted by the procurement team and project "
            "managers. If that's you, please contact the administrator."
        ),
    },
    "choose": {
        "ru": "Что передаёте?",
        "en": "What are you submitting?",
    },
}
KIND_EN = {PLAN: "Plan", FACT: "Actuals"}


class ExpStates(StatesGroup):
    choosing = State()
    waiting = State()
    confirming = State()


def _tx(key: str, lang: str, **kw) -> str:
    return TXT[key]["en" if lang == "en" else "ru"].format(**kw)


def _identity(user, config: Config) -> tuple[dict | None, bool]:
    """(сотрудник из команды или None, тестовый режим админа)."""
    member = member_by_username(user.username)
    if member:
        return member, False
    return None, config.is_admin(user.id)


def _test_member(user, role: str) -> dict:
    return {"username": f"admin_test_{user.id}", "name": "Тест (админ)", "role": role}


def _submit_button(kind: str, period: Period) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=BTN_SUBMIT, callback_data=f"{CB_START}:{kind}:{period.key}"
    )]])


def _confirm_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Верно / Correct", callback_data=CB_OK),
        InlineKeyboardButton(text="✏️ Исправить / Edit", callback_data=CB_REDO),
    ]])


def _kinds_menu(roles: list[str]) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=KIND_BUTTONS[(role, kind)])]
        for role in roles
        for kind in (PLAN, FACT)
    ]
    rows.append([KeyboardButton(text=kb.BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


async def _start_input(
    message: Message, state: FSMContext, member: dict, period: Period, test: bool, lang: str
) -> None:
    await state.set_state(ExpStates.waiting)
    await state.update_data(
        member=member, kind=period.kind, key=period.key, test=test
    )
    text = _tx(
        "ask", lang, icon=ICON[period.kind], kind=KIND_RU[period.kind],
        kind_en=KIND_EN[period.kind], period=period.label,
        example=html.escape(FORMAT_EXAMPLE),
    )
    if test:
        text += f"\n\n🧪 Тестовый режим: данные пойдут на лист «{TEST_WORKSHEET}»."
    await message.answer(text, reply_markup=kb.cancel_menu("381-03 Название — сумма"))


# --- вход: кнопка в меню ------------------------------------------------------

@router.message(F.text == kb.BTN_SEND_DATA)
async def enter_from_menu(
    message: Message, state: FSMContext, config: Config, users: UserRegistry
) -> None:
    lang = users.get_lang(message.from_user.id)
    member, test = _identity(message.from_user, config)
    if not member and not test:
        await message.answer(_tx("not_member", lang))
        return
    roles = [member["role"]] if member else [KOMPLEKT, PM]
    await state.set_state(ExpStates.choosing)
    await state.update_data(test=test)
    text = _tx("choose", lang)
    if test:
        text = "🧪 Вас нет в списке сотрудников — тестовый режим.\n\n" + text
    await message.answer(text, reply_markup=_kinds_menu(roles))


@router.message(ExpStates.choosing, F.text.in_(list(KIND_BUTTONS.values())))
async def choose_kind(
    message: Message, state: FSMContext, config: Config, users: UserRegistry
) -> None:
    lang = users.get_lang(message.from_user.id)
    role, kind = next(k for k, v in KIND_BUTTONS.items() if v == message.text)
    member, test = _identity(message.from_user, config)
    if member and member["role"] != role:
        await message.answer(_tx("choose", lang), reply_markup=_kinds_menu([member["role"]]))
        return
    if not member and not test:
        await state.clear()
        return
    period = period_for(role, kind, now_dubai().date())
    await _start_input(
        message, state, member or _test_member(message.from_user, role), period, test, lang
    )


# --- вход: кнопка в напоминании ---------------------------------------------

@router.callback_query(F.data.startswith(f"{CB_START}:"))
async def enter_from_reminder(
    callback: CallbackQuery, state: FSMContext, config: Config, users: UserRegistry
) -> None:
    await callback.answer()
    lang = users.get_lang(callback.from_user.id)
    member, test = _identity(callback.from_user, config)
    try:
        _, kind, key = callback.data.split(":", 2)
    except ValueError:
        return
    role = member["role"] if member else (KOMPLEKT if key.startswith("W") else PM)
    period = period_from_key(role, kind, key)
    if period is None:
        return
    if not member and not test:
        await callback.message.answer(_tx("not_member", lang))
        return
    await _start_input(
        callback.message, state, member or _test_member(callback.from_user, role),
        period, test, lang,
    )


# --- отмена ------------------------------------------------------------------

@router.message(ExpStates.choosing, F.text == kb.BTN_CANCEL)
@router.message(ExpStates.waiting, F.text == kb.BTN_CANCEL)
@router.message(ExpStates.confirming, F.text == kb.BTN_CANCEL)
async def cancel(
    message: Message, state: FSMContext, config: Config, users: UserRegistry
) -> None:
    await state.clear()
    lang = users.get_lang(message.from_user.id)
    await message.answer(
        t("cancelled", lang),
        reply_markup=kb.main_menu(config.is_admin(message.from_user.id)),
    )


@router.message(ExpStates.choosing)
async def choosing_other(message: Message, state: FSMContext, config: Config, users: UserRegistry) -> None:
    lang = users.get_lang(message.from_user.id)
    member, _ = _identity(message.from_user, config)
    roles = [member["role"]] if member else [KOMPLEKT, PM]
    await message.answer(_tx("choose", lang), reply_markup=_kinds_menu(roles))


# --- приём списка ------------------------------------------------------------

@router.message(ExpStates.waiting, F.text)
@router.message(ExpStates.confirming, F.text)
async def receive_list(
    message: Message,
    state: FSMContext,
    config: Config,
    users: UserRegistry,
    knowledge: KnowledgeService,
    expense_store: ExpenseStore,
) -> None:
    lang = users.get_lang(message.from_user.id)
    data = await state.get_data()
    member = data["member"]
    period = period_from_key(member["role"], data["kind"], data["key"])
    example = html.escape(FORMAT_EXAMPLE)

    simple = parse_simple(message.text)
    if simple is not None:
        items = [{"project": p, "amounts": [a]} for p, a in simple]
    elif knowledge.answerer is not None:
        await message.bot.send_chat_action(message.chat.id, "typing")
        try:
            items = await knowledge.answerer.extract_expenses(message.text)
        except Exception as err:  # noqa: BLE001
            logging.exception("План/факт: Claude не смог разобрать сообщение")
            await alert_admin(
                message.bot, config,
                "⚠️ План/факт: Claude не смог разобрать сообщение сотрудника.\n"
                f"Причина: {html.escape(describe_error(err))}",
            )
            await message.answer(_tx("parse_fail", lang, example=example))
            return
    else:
        await message.answer(_tx("parse_fail", lang, example=example))
        return

    ok, errors = validate(items)
    if errors:
        lines = "\n".join(
            f"• «{html.escape(line)}» — {html.escape(reason)}" for line, reason in errors
        )
        await state.set_state(ExpStates.waiting)
        await message.answer(_tx("bad_format", lang, lines=lines, example=example))
        return
    if not ok:
        await state.set_state(ExpStates.waiting)
        await message.answer(_tx("nothing", lang, example=example))
        return

    total = sum(a for _, a in ok)
    prev = expense_store.submission(member["username"], period.kind, period.key)
    again = _tx("again", lang, prev=fmt_amount(prev["total"])) if prev else ""
    lines = "\n".join(f"{html.escape(p)} — {fmt_amount(a)}" for p, a in ok)
    await state.update_data(items=ok, total=total)
    await state.set_state(ExpStates.confirming)
    await message.answer(
        _tx(
            "confirm", lang, icon=ICON[period.kind], kind=KIND_RU[period.kind],
            kind_en=KIND_EN[period.kind], period=period.label, lines=lines,
            total=fmt_amount(total), again=again,
        ),
        reply_markup=_confirm_buttons(),
    )


@router.message(ExpStates.waiting)
async def not_text(message: Message, users: UserRegistry) -> None:
    lang = users.get_lang(message.from_user.id)
    await message.answer(_tx("need_text", lang))


@router.callback_query(ExpStates.confirming, F.data == CB_REDO)
async def redo(callback: CallbackQuery, state: FSMContext, users: UserRegistry) -> None:
    await callback.answer()
    lang = users.get_lang(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(ExpStates.waiting)
    data = await state.get_data()
    member = data["member"]
    period = period_from_key(member["role"], data["kind"], data["key"])
    await _start_input(callback.message, state, member, period, data.get("test", False), lang)


@router.callback_query(ExpStates.confirming, F.data == CB_OK)
async def confirm(
    callback: CallbackQuery,
    state: FSMContext,
    config: Config,
    users: UserRegistry,
    sheets: SheetsClient | None,
    expense_store: ExpenseStore,
) -> None:
    await callback.answer()
    lang = users.get_lang(callback.from_user.id)
    is_admin = config.is_admin(callback.from_user.id)
    data = await state.get_data()
    await state.clear()
    member = data["member"]
    test = data.get("test", False)
    period = period_from_key(member["role"], data["kind"], data["key"])
    items = [(p, float(a)) for p, a in data["items"]]
    total = float(data["total"])
    prev = expense_store.submission(member["username"], period.kind, period.key)
    await callback.message.edit_reply_markup(reply_markup=None)

    try:
        if sheets is None or not config.expenses_sheet_id:
            raise RuntimeError("Google Sheets не подключены")
        await asyncio.to_thread(
            lambda: write_submission(
                sheets.spreadsheet(config.expenses_sheet_id), member, period, items,
                total, prev["total"] if prev else None, test,
            )
        )
        reply = "saved"
    except Exception as err:  # noqa: BLE001
        logging.exception("План/факт: ошибка записи в таблицу")
        problem = sheets.explain_error(err) if sheets else str(err)
        body = "\n".join(f"{p} — {fmt_amount(a)}" for p, a in items)
        delivered = await alert_admin(
            callback.bot, config,
            "⚠️ <b>План/факт не записался в таблицу</b>\n"
            f"Причина: {html.escape(problem)}\n\nДанные целиком 👇",
            f"{member['name']} · {KIND_RU[period.kind]} · {period.label}\n\n"
            f"{body}\n\nИтого: {fmt_amount(total)} AED",
        )
        if not delivered:
            await callback.message.answer(
                t("submit_error", lang), reply_markup=kb.main_menu(is_admin)
            )
            return
        reply = "saved_backup"

    expense_store.record(member["username"], period.kind, period.key, total)
    await callback.message.answer(_tx(reply, lang), reply_markup=kb.main_menu(is_admin))


# --- команды администратора --------------------------------------------------

@router.message(Command("team"))
async def team_status(
    message: Message, config: Config, users: UserRegistry, expense_store: ExpenseStore
) -> None:
    """Кто из команды подключён к боту и кто уже сдал данные за текущий период."""
    if not config.is_admin(message.from_user.id):
        return
    today = now_dubai().date()
    lines = ["👥 <b>План/факт: команда</b>", ""]
    for role, title in ((KOMPLEKT, "Комплектаторы"), (PM, "Проджект-менеджеры")):
        plan, fact = period_for(role, PLAN, today), period_for(role, FACT, today)
        lines.append(f"<b>{title}</b> (план: {plan.label}, факт: {fact.label})")
        for m in members(role):
            linked = "✅" if users.find_by_username(m["username"]) else "❌ не нажал(а) /start"
            got_plan = "есть" if expense_store.submission(m["username"], PLAN, plan.key) else "—"
            got_fact = "есть" if expense_store.submission(m["username"], FACT, fact.key) else "—"
            lines.append(
                f"• {html.escape(m['name'])} (@{m['username']}) {linked} · "
                f"план: {got_plan} · факт: {got_fact}"
            )
        lines.append("")
    await message.answer("\n".join(lines))


@router.message(Command("exp_test"))
async def send_test_reminders(message: Message, config: Config) -> None:
    """Присылает админу все виды первых напоминаний — посмотреть тексты и кнопки."""
    if not config.is_admin(message.from_user.id):
        return
    now = now_dubai()
    for role in (KOMPLEKT, PM):
        for kind in (PLAN, FACT):
            period = period_for(role, kind, now.date())
            r = Reminder(role, kind, True, now)
            await message.answer(
                f"🧪 <i>{'Комплектаторы' if role == KOMPLEKT else 'ПМ'}, "
                f"{KIND_RU[kind].lower()}:</i>\n\n" + html.escape(reminder_text(r, period), quote=False),
                reply_markup=_submit_button(kind, period),
            )


# --- расписание --------------------------------------------------------------

async def _tick(bot, config: Config, users: UserRegistry, store: ExpenseStore, sheets) -> None:
    now = now_dubai()
    today = now.date()

    # 1-го числа заранее создаём лист нового месяца.
    month_key = f"sheet|{today:%Y-%m}"
    if today.day == 1 and now.hour >= 9 and sheets and not store.was_sent(month_key):
        store.mark_sent(month_key)
        try:
            await asyncio.to_thread(
                ensure_current_month, sheets.spreadsheet(config.expenses_sheet_id), today
            )
        except Exception:  # noqa: BLE001
            logging.exception("План/факт: не удалось создать лист нового месяца")

    for r in reminders_on(today):
        if now < r.at or now - r.at > dt.timedelta(hours=3):
            continue
        event = f"{r.at:%Y-%m-%d %H:%M}|{r.role}|{r.kind}|{'1' if r.first else '2'}"
        if store.was_sent(event):
            continue
        store.mark_sent(event)
        period = period_for(r.role, r.kind, today)
        text = html.escape(reminder_text(r, period), quote=False)
        unreachable = []
        for m in members(r.role):
            if not r.first and store.submission(m["username"], r.kind, period.key):
                continue
            uid = users.find_by_username(m["username"])
            if uid is None:
                unreachable.append(m)
                continue
            try:
                await bot.send_message(uid, text, reply_markup=_submit_button(r.kind, period))
            except TelegramForbiddenError:
                unreachable.append(m)
            except Exception:  # noqa: BLE001
                logging.exception("План/факт: не удалось отправить напоминание %s", m["name"])
            await asyncio.sleep(0.1)
        logging.info("План/факт: напоминание %s отправлено", event)
        if unreachable and r.first:
            names = "\n".join(
                f"• {html.escape(m['name'])} (@{m['username']})" for m in unreachable
            )
            await alert_admin(
                bot, config,
                "⚠️ План/факт: не смог отправить напоминание — эти сотрудники ещё не "
                f"нажали /start в боте (или заблокировали его):\n{names}",
            )


async def reminders_loop(bot, config: Config, users: UserRegistry, store: ExpenseStore, sheets) -> None:
    """Каждые 30 секунд проверяет, не пора ли отправить напоминание."""
    while True:
        try:
            await _tick(bot, config, users, store, sheets)
        except Exception:  # noqa: BLE001
            logging.exception("План/факт: ошибка в расписании напоминаний")
        await asyncio.sleep(30)
