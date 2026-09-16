"""Этап 6: рассылки и объявления (только для админа).

Поток: «📢 Рассылка» → ввод текста → предпросмотр → подтверждение →
отправка всем с ограничением скорости → отчёт «доставлено/заблокировано».
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
from app.users import UserRegistry
from config import Config

router = Router()

# Пауза между сообщениями: ~20 в секунду — с запасом под лимиты Telegram.
SEND_DELAY = 0.05


class BroadcastStates(StatesGroup):
    writing = State()
    confirming = State()


@router.message(F.text == kb.BTN_BROADCAST)
async def start_broadcast(
    message: Message, state: FSMContext, config: Config, users: UserRegistry
) -> None:
    if not config.is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastStates.writing)
    await message.answer(
        "📢 <b>Рассылка</b>\n\n"
        f"Напишите текст объявления — оно уйдёт всем, кто пользовался ботом "
        f"(сейчас это <b>{users.count()}</b> чел.).\n\n"
        "Можно оформлять жирным/курсивом через панель форматирования Telegram.\n"
        "Отмена — кнопка ниже.",
        reply_markup=kb.cancel_menu(),
    )


@router.message(BroadcastStates.writing, F.text == kb.BTN_CANCEL)
async def cancel_writing(
    message: Message, state: FSMContext, config: Config
) -> None:
    await state.clear()
    await message.answer(
        "Рассылка отменена.",
        reply_markup=kb.main_menu(config.is_admin(message.from_user.id)),
    )


@router.message(BroadcastStates.writing, F.text)
async def preview(message: Message, state: FSMContext) -> None:
    # Сохраняем текст с форматированием (html_text сохраняет жирный/курсив).
    await state.update_data(html_text=message.html_text)
    await state.set_state(BroadcastStates.confirming)

    await message.answer("👇 Вот так будет выглядеть объявление:")
    await message.answer(message.html_text, disable_web_page_preview=True)
    await message.answer(
        "Отправить это объявление всем?", reply_markup=kb.broadcast_confirm()
    )


@router.callback_query(
    BroadcastStates.confirming, F.data == kb.CB_BROADCAST_CANCEL
)
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
    text = data.get("html_text", "")
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Начинаю рассылку…")

    ids = users.all_ids()
    status = await callback.message.answer(f"📤 Отправляю {len(ids)} получателям…")

    delivered = blocked = errors = 0
    for uid in ids:
        try:
            await callback.bot.send_message(uid, text, disable_web_page_preview=True)
            delivered += 1
        except TelegramForbiddenError:
            # Пользователь заблокировал бота или удалил чат.
            blocked += 1
        except TelegramRetryAfter as err:
            # Telegram просит подождать — ждём и пробуем ещё раз.
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
        f"🚫 Заблокировали бота: <b>{blocked}</b>\n"
    )
    if errors:
        report += f"⚠️ Ошибки: <b>{errors}</b>\n"

    await status.edit_text(report)
    await callback.message.answer(
        "Готово 👍", reply_markup=kb.main_menu(is_admin=True)
    )
