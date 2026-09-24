"""Функция «Договорённости с клиентом».

Поток: кнопка → номер проекта (123-45) → голосовое → распознавание (Whisper) →
структурирование (Claude, строго без домыслов) → строка в отдельную Google-таблицу.
Сотруднику — только подтверждение, без текста расшифровки.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import re
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app import keyboards as kb
from app.i18n import t
from app.knowledge_service import KnowledgeService
from app.sheets import SheetsClient
from app.transcribe import Transcriber
from app.users import UserRegistry
from config import Config

router = Router()

AGREEMENTS_SHEET_ENV = "GOOGLE_SHEET_AGREEMENTS"
AGREEMENTS_WORKSHEET = "Договорённости"
PROJECT_RE = re.compile(r"^\d{3}-\d{2}$")


class AgreementStates(StatesGroup):
    project = State()
    voice = State()


def _ready(config: Config, sheets: SheetsClient | None) -> bool:
    return sheets is not None and bool(config.sheet_ids.get(AGREEMENTS_SHEET_ENV))


@router.message(F.text == kb.BTN_AGREEMENTS)
async def enter_agreements(
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
    await state.set_state(AgreementStates.project)
    await message.answer(t("agr_ask_project", lang), reply_markup=kb.cancel_menu())


@router.message(AgreementStates.project, F.text == kb.BTN_CANCEL)
@router.message(AgreementStates.voice, F.text == kb.BTN_CANCEL)
async def cancel(
    message: Message, state: FSMContext, config: Config, users: UserRegistry
) -> None:
    await state.clear()
    lang = users.get_lang(message.from_user.id)
    await message.answer(
        t("cancelled", lang),
        reply_markup=kb.main_menu(config.is_admin(message.from_user.id)),
    )


@router.message(AgreementStates.project, F.text)
async def get_project(
    message: Message, state: FSMContext, users: UserRegistry
) -> None:
    lang = users.get_lang(message.from_user.id)
    number = message.text.strip()
    if not PROJECT_RE.match(number):
        await message.answer(t("agr_bad_project", lang), reply_markup=kb.cancel_menu())
        return
    await state.update_data(project=number)
    await state.set_state(AgreementStates.voice)
    await message.answer(t("agr_ask_voice", lang), reply_markup=kb.cancel_menu())


@router.message(AgreementStates.voice, F.voice)
async def get_voice(
    message: Message,
    state: FSMContext,
    config: Config,
    sheets: SheetsClient | None,
    users: UserRegistry,
    knowledge: KnowledgeService,
    transcriber: Transcriber,
) -> None:
    lang = users.get_lang(message.from_user.id)
    is_admin = config.is_admin(message.from_user.id)
    data = await state.get_data()
    project = data.get("project", "")
    await state.clear()

    sheet_id = config.sheet_ids.get(AGREEMENTS_SHEET_ENV)
    if not _ready(config, sheets) or knowledge.answerer is None:
        await message.answer(
            t("agr_not_configured", lang), reply_markup=kb.main_menu(is_admin)
        )
        return

    await message.answer(t("agr_processing", lang))
    await message.bot.send_chat_action(message.chat.id, "typing")

    path = f"/tmp/voice_{message.from_user.id}_{uuid.uuid4().hex}.oga"
    try:
        file = await message.bot.get_file(message.voice.file_id)
        await message.bot.download_file(file.file_path, destination=path)
        transcript, detected = await asyncio.to_thread(transcriber.transcribe, path)
    except Exception:  # noqa: BLE001
        logging.exception("Ошибка распознавания голосового")
        await message.answer(t("agr_error", lang), reply_markup=kb.main_menu(is_admin))
        return
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if not transcript:
        await message.answer(t("agr_error", lang), reply_markup=kb.main_menu(is_admin))
        return

    try:
        structured = await knowledge.answerer.structure_notes(
            transcript, detected or lang
        )
        now = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
        name = message.from_user.full_name
        header = ["Дата", "Сотрудник", "Проект", "Расшифровка"]
        row = [now, name, project, structured or transcript]
        await asyncio.to_thread(
            sheets.append_row, sheet_id, AGREEMENTS_WORKSHEET, header, row
        )
    except Exception:  # noqa: BLE001
        logging.exception("Ошибка сохранения договорённостей")
        await message.answer(t("agr_error", lang), reply_markup=kb.main_menu(is_admin))
        return

    await message.answer(t("agr_saved", lang), reply_markup=kb.main_menu(is_admin))

    # Короткое уведомление администратору (только ему, от этого же бота).
    if config.admin_id and message.from_user.id != config.admin_id:
        try:
            await message.bot.send_message(
                config.admin_id,
                "🤝 Сотрудник оставил новую договорённость с клиентом.",
            )
        except Exception:  # noqa: BLE001
            logging.warning("Не удалось отправить уведомление админу о договорённости")


@router.message(AgreementStates.voice)
async def not_a_voice(message: Message, users: UserRegistry) -> None:
    lang = users.get_lang(message.from_user.id)
    await message.answer(t("agr_need_voice", lang), reply_markup=kb.cancel_menu())
