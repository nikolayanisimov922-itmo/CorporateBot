"""Функция «Черный ящик» — фиксация проблем и сложных кейсов команды.

Поток: кнопка → отдел (кнопками) → рассказ голосовым или текстом (голос →
Whisper) → серьёзность (кнопками) → Claude аккуратно оформляет «что произошло /
выводы» (строго без домыслов) → строка в Google-таблицу «Черный ящик»
(отдельный лист). Админу — уведомление с отделом и серьёзностью.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app import keyboards as kb
from app.blackbox import (
    BLACKBOX_HEADER,
    BLACKBOX_SHEET_ENV,
    BLACKBOX_WORKSHEET,
    DEPARTMENTS,
    SEVERITIES,
)
from app.i18n import t
from app.knowledge_service import KnowledgeService
from app.sheets import SheetsClient
from app.transcribe import Transcriber, voice_to_text
from app.users import UserRegistry
from config import Config

router = Router()


class BlackBoxStates(StatesGroup):
    department = State()
    story = State()
    severity = State()


def _ready(config: Config, sheets: SheetsClient | None) -> bool:
    return sheets is not None and bool(config.sheet_ids.get(BLACKBOX_SHEET_ENV))


@router.message(F.text == kb.BTN_BLACKBOX)
async def enter_blackbox(
    message: Message,
    state: FSMContext,
    config: Config,
    sheets: SheetsClient | None,
    users: UserRegistry,
) -> None:
    lang = users.get_lang(message.from_user.id)
    if not _ready(config, sheets):
        await message.answer(t("agr_not_configured", lang))
        return
    await state.set_state(BlackBoxStates.department)
    await message.answer(t("bb_ask_department", lang), reply_markup=kb.departments_menu())


@router.message(BlackBoxStates.department, F.text == kb.BTN_CANCEL)
@router.message(BlackBoxStates.story, F.text == kb.BTN_CANCEL)
@router.message(BlackBoxStates.severity, F.text == kb.BTN_CANCEL)
async def cancel(
    message: Message, state: FSMContext, config: Config, users: UserRegistry
) -> None:
    await state.clear()
    lang = users.get_lang(message.from_user.id)
    await message.answer(
        t("cancelled", lang),
        reply_markup=kb.main_menu(config.is_admin(message.from_user.id)),
    )


@router.message(BlackBoxStates.department, F.text.in_(DEPARTMENTS))
async def get_department(
    message: Message, state: FSMContext, users: UserRegistry
) -> None:
    lang = users.get_lang(message.from_user.id)
    await state.update_data(department=message.text)
    await state.set_state(BlackBoxStates.story)
    await message.answer(t("bb_ask_story", lang), reply_markup=kb.cancel_menu())


@router.message(BlackBoxStates.department)
async def department_not_picked(message: Message, users: UserRegistry) -> None:
    lang = users.get_lang(message.from_user.id)
    await message.answer(
        t("bb_pick_department", lang), reply_markup=kb.departments_menu()
    )


async def _ask_severity(message: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(BlackBoxStates.severity)
    await message.answer(t("bb_ask_severity", lang), reply_markup=kb.severity_menu())


@router.message(BlackBoxStates.story, F.voice)
async def get_story_voice(
    message: Message,
    state: FSMContext,
    users: UserRegistry,
    transcriber: Transcriber,
) -> None:
    lang = users.get_lang(message.from_user.id)
    await message.answer(t("agr_processing", lang))
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        text, _ = await voice_to_text(message.bot, message.voice, transcriber)
    except Exception:  # noqa: BLE001
        logging.exception("Черный ящик: ошибка распознавания голосового")
        text = ""
    if not text:
        await message.answer(t("bb_voice_error", lang), reply_markup=kb.cancel_menu())
        return
    await state.update_data(story=text)
    await _ask_severity(message, state, lang)


@router.message(BlackBoxStates.story, F.text)
async def get_story_text(
    message: Message, state: FSMContext, users: UserRegistry
) -> None:
    lang = users.get_lang(message.from_user.id)
    await state.update_data(story=message.text.strip())
    await _ask_severity(message, state, lang)


@router.message(BlackBoxStates.story)
async def story_not_given(message: Message, users: UserRegistry) -> None:
    lang = users.get_lang(message.from_user.id)
    await message.answer(t("bb_need_story", lang), reply_markup=kb.cancel_menu())


@router.message(BlackBoxStates.severity, F.text.in_(list(SEVERITIES)))
async def get_severity(
    message: Message,
    state: FSMContext,
    config: Config,
    sheets: SheetsClient | None,
    users: UserRegistry,
    knowledge: KnowledgeService,
) -> None:
    lang = users.get_lang(message.from_user.id)
    is_admin = config.is_admin(message.from_user.id)
    severity = SEVERITIES[message.text]
    data = await state.get_data()
    department = data.get("department", "")
    story = data.get("story", "")

    sheet_id = config.sheet_ids.get(BLACKBOX_SHEET_ENV)
    if not _ready(config, sheets):
        await state.clear()
        await message.answer(
            t("agr_not_configured", lang), reply_markup=kb.main_menu(is_admin)
        )
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    # Оформление через Claude. Если Claude недоступен — сохраняем рассказ как есть,
    # чтобы кейс не потерялся.
    description = story
    if knowledge.answerer is not None:
        try:
            description = await knowledge.answerer.structure_problem(story) or story
        except Exception:  # noqa: BLE001
            logging.exception("Черный ящик: Claude не смог оформить текст")

    user = message.from_user
    who = user.full_name + (f" (@{user.username})" if user.username else "")
    row = [
        dt.datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        who,
        department,
        severity,
        description,
    ]
    try:
        await asyncio.to_thread(
            sheets.append_row, sheet_id, BLACKBOX_WORKSHEET, BLACKBOX_HEADER, row
        )
    except Exception:  # noqa: BLE001
        # Состояние не сбрасываем: человек может нажать серьёзность ещё раз.
        logging.exception("Черный ящик: ошибка записи в таблицу")
        await message.answer(t("submit_error", lang), reply_markup=kb.severity_menu())
        return

    await state.clear()
    await message.answer(t("bb_saved", lang), reply_markup=kb.main_menu(is_admin))

    if config.admin_id and user.id != config.admin_id:
        icon = {"Критично": "🔴", "Средне": "🟠"}.get(severity, "🟢")
        try:
            await message.bot.send_message(
                config.admin_id,
                f"⬛ Новый кейс в «Черном ящике»\n"
                f"{icon} {severity} · {department}",
            )
        except Exception:  # noqa: BLE001
            logging.warning("Не удалось отправить уведомление админу о черном ящике")


@router.message(BlackBoxStates.severity)
async def severity_not_picked(message: Message, users: UserRegistry) -> None:
    lang = users.get_lang(message.from_user.id)
    await message.answer(t("bb_pick_severity", lang), reply_markup=kb.severity_menu())
