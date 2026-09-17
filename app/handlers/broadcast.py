"""Этап 6: рассылки и объявления (только для админа).

Типы:
  • Общая рассылка — всем пользователям, текст вводит админ.
  • Пресеты (ПМ/Комплектаторы) — конкретной группе по списку ID, готовый текст.

Поток: «📢 Рассылка» → выбор типа → (для общей: ввод текста) → предпросмотр →
подтверждение → отправка с ограничением скорости → отчёт «доставлено/заблокировано».
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.broadcasts import GENERAL_TITLE, preset_by_title
from app.users import UserRegistry
from config import Config

router = Router()

# Пауза между сообщениями: ~20 в секунду — с запасом под лимиты Telegram.
SEND_DELAY = 0.05


class BroadcastStates(StatesGroup):
    choosing = State()
    writing = State()
    confirming = State()


@router.message(F.text == kb.BTN_BROADCAST)
async def start_broadcast(
    message: Message, state: FSMContext, config: Config
) -> None:
    if not config.is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastStates.choosing)
    await message.answer(
        "📢 <b>Рассылка</b>\n\nВыберите тип рассылки:",
        reply_markup=kb.broadcast_menu(),
    )


@router.message(BroadcastStates.choosing, F.text == kb.BTN_CANCEL)
async def cancel_choosing(
    message: Message, state: FSMContext, config: Config
) -> None:
    await state.clear()
    await message.answer(
        "Отменено.", reply_markup=kb.main_menu(config.is_admin(message.from_user.id))
    )


@router.message(BroadcastStates.choosing, F.text == GENERAL_TITLE)
async def choose_general(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.writing)
    await message.answer(
        "Напишите текст объявления для <b>всех</b> пользователей.\n"
        "Можно оформлять жирным/курсивом через форматирование Telegram.",
        reply_markup=kb.cancel_menu("Введите текст объявления…"),
    )


@router.message(BroadcastStates.choosing, F.text)
async def choose_preset(
    message: Message, state: FSMContext, config: Config
) -> None:
    preset = preset_by_title(message.text)
    if preset is None:
        await message.answer(
            "Пожалуйста, выберите тип рассылки кнопкой ниже.",
            reply_markup=kb.broadcast_menu(),
        )
        return

    ids = config.broadcast_ids.get(preset["ids_env"])
    if not ids:
        await message.answer(
            f"⚠️ Для «{preset['title']}» ещё не заданы получатели.\n"
            f"Добавьте их ID в .env (переменная <code>{preset['ids_env']}</code>) "
            "и перезапустите бота.",
            reply_markup=kb.broadcast_menu(),
        )
        return

    # Готовим адресную рассылку с готовым текстом.
    await state.update_data(text=preset["message"], target_ids=ids)
    await state.set_state(BroadcastStates.confirming)
    await message.answer("👇 Вот так будет выглядеть рассылка:")
    await message.answer(preset["message"], disable_web_page_preview=True)
    await message.answer(
        f"Отправить <b>{len(ids)}</b> получателям группы «{preset['title']}»?",
        reply_markup=kb.broadcast_confirm(),
    )


@router.message(BroadcastStates.writing, F.text == kb.BTN_CANCEL)
async def cancel_writing(
    message: Message, state: FSMContext, config: Config
) -> None:
    await state.clear()
    await message.answer(
        "Отменено.", reply_markup=kb.main_menu(config.is_admin(message.from_user.id))
    )


@router.message(BroadcastStates.writing, F.text)
async def preview_general(message: Message, state: FSMContext) -> None:
    # target_ids=None означает «всем пользователям».
    await state.update_data(text=message.html_text, target_ids=None)
    await state.set_state(BroadcastStates.confirming)
    await message.answer("👇 Вот так будет выглядеть объявление:")
    await message.answer(message.html_text, disable_web_page_preview=True)
    await message.answer(
        "Отправить это объявление <b>всем</b>?", reply_markup=kb.broadcast_confirm()
    )


@router.callback_query(BroadcastStates.confirming, F.data == kb.CB_BROADCAST_CANCEL)
async def confirm_cancel(
    callback: CallbackQuery, state: FSMContext, config: Config
) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Рассылка отменена.",
        reply_markup=kb.main_menu(config.is_admin(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(BroadcastStates.confirming, F.data == kb.CB_BROADCAST_SEND)
async def confirm_send(
    callback: CallbackQuery, state: FSMContext, users: UserRegistry
) -> None:
    data = await state.get_data()
    text = data.get("text", "")
    target_ids = data.get("target_ids")  # None -> всем
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Начинаю рассылку…")

    ids = target_ids if target_ids is not None else users.all_ids()
    status = await callback.message.answer(f"📤 Отправляю {len(ids)} получателям…")

    delivered = blocked = errors = 0
    for uid in ids:
        try:
            await callback.bot.send_message(uid, text, disable_web_page_preview=True)
            delivered += 1
        except TelegramForbiddenError:
            blocked += 1
        except TelegramRetryAfter as err:
            await asyncio.sleep(err.retry_after)
            try:
                await callback.bot.send_message(
                    uid, text, disable_web_page_preview=True
                )
                delivered += 1
            except Exception:  # noqa: BLE001
                errors += 1
        except Exception:  # noqa: BLE001
            logging.exception("Ошибка отправки пользователю %s", uid)
            errors += 1
        await asyncio.sleep(SEND_DELAY)

    report = (
        "✅ <b>Рассылка завершена</b>\n\n"
        f"📨 Доставлено: <b>{delivered}</b>\n"
        f"🚫 Заблокировали бота / не запускали: <b>{blocked}</b>\n"
    )
    if errors:
        report += f"⚠️ Ошибки: <b>{errors}</b>\n"

    await status.edit_text(report)
    await callback.message.answer(
        "Готово 👍", reply_markup=kb.main_menu(is_admin=True)
    )
