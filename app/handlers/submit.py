"""Этап 7: приём данных от сотрудника → строка в Google Sheets."""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app import keyboards as kb
from app.forms import FORMS, form_by_title
from app.sheets import SheetsClient
from config import Config

router = Router()


class SubmitStates(StatesGroup):
    choosing = State()
    filling = State()


@router.message(F.text == kb.BTN_SEND_DATA)
async def enter_submit(
    message: Message,
    state: FSMContext,
    config: Config,
    sheets: SheetsClient | None,
) -> None:
    if sheets is None or not config.sheet_ids:
        await message.answer(
            "⚠️ Приём данных пока не настроен (не подключена Google-таблица). "
            "Загляните позже."
        )
        return
    await state.set_state(SubmitStates.choosing)
    await message.answer(
        "📤 <b>Передать данные</b>\n\nВыберите, что хотите отправить:",
        reply_markup=kb.submit_menu(config.sheet_ids),
    )


@router.message(SubmitStates.choosing, F.text == kb.BTN_CANCEL)
async def cancel_choosing(
    message: Message, state: FSMContext, config: Config
) -> None:
    await state.clear()
    await message.answer(
        "Отменено.", reply_markup=kb.main_menu(config.is_admin(message.from_user.id))
    )


@router.message(SubmitStates.choosing, F.text)
async def choose_category(
    message: Message, state: FSMContext, config: Config
) -> None:
    form = form_by_title(message.text)
    if form is None or form["sheet_env"] not in config.sheet_ids:
        await message.answer(
            "Пожалуйста, выберите тип кнопкой ниже.",
            reply_markup=kb.submit_menu(config.sheet_ids),
        )
        return
    await state.update_data(form_key=form["key"], field_index=0, answers={})
    await state.set_state(SubmitStates.filling)
    await message.answer(
        f"{form['title']}\n\n{form['fields'][0]['q']}",
        reply_markup=kb.cancel_menu("Введите ответ…"),
    )


@router.message(SubmitStates.filling, F.text == kb.BTN_CANCEL)
async def cancel_filling(
    message: Message, state: FSMContext, config: Config
) -> None:
    await state.clear()
    await message.answer(
        "Отменено.", reply_markup=kb.main_menu(config.is_admin(message.from_user.id))
    )


@router.message(SubmitStates.filling, F.text)
async def fill_field(
    message: Message,
    state: FSMContext,
    config: Config,
    sheets: SheetsClient | None,
) -> None:
    data = await state.get_data()
    form = FORMS[data["form_key"]]
    idx = data["field_index"]
    answers = dict(data["answers"])

    answers[form["fields"][idx]["key"]] = message.text.strip()
    idx += 1

    # Ещё есть вопросы — задаём следующий.
    if idx < len(form["fields"]):
        await state.update_data(field_index=idx, answers=answers)
        await message.answer(
            form["fields"][idx]["q"], reply_markup=kb.cancel_menu("Введите ответ…")
        )
        return

    # Все ответы собраны — пишем строку в нужную таблицу.
    await state.clear()
    is_admin = config.is_admin(message.from_user.id)

    sheet_id = config.sheet_ids.get(form["sheet_env"])
    if sheets is None or not sheet_id:
        await message.answer(
            "⚠️ Google-таблица недоступна, запись не сохранена.",
            reply_markup=kb.main_menu(is_admin),
        )
        return

    now = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    name = message.from_user.full_name
    uid = message.from_user.id
    header = ["Дата", "Сотрудник", "ID"] + [f["label"] for f in form["fields"]]
    row = [now, name, str(uid)] + [answers[f["key"]] for f in form["fields"]]

    try:
        await asyncio.to_thread(
            sheets.append_row, sheet_id, form["worksheet"], header, row
        )
    except Exception:  # noqa: BLE001
        logging.exception("Ошибка записи в Google Sheets")
        await message.answer(
            "❌ Не получилось сохранить данные. Попробуйте позже или сообщите администратору.",
            reply_markup=kb.main_menu(is_admin),
        )
        return

    await message.answer(
        f"✅ Готово! Ваша запись «{form['title']}» сохранена. Спасибо!",
        reply_markup=kb.main_menu(is_admin),
    )

    # Уведомление админу о новой записи (если это не он сам).
    if config.admin_id and uid != config.admin_id:
        summary = "\n".join(
            f"• {f['label']}: {html.escape(answers[f['key']])}" for f in form["fields"]
        )
        try:
            await message.bot.send_message(
                config.admin_id,
                f"📥 Новая запись «{html.escape(form['title'])}» "
                f"от {html.escape(name)}:\n{summary}",
            )
        except Exception:  # noqa: BLE001
            logging.warning("Не удалось уведомить админа о новой записи")
