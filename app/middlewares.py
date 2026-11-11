"""Middleware: запоминает каждого пользователя, который пишет боту (этап 6)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.keyboards import BTN_CANCEL, MAIN_BUTTONS, current_user_id
from app.users import UserRegistry


class RegisterUserMiddleware(BaseMiddleware):
    def __init__(self, users: UserRegistry) -> None:
        self.users = users

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None and not user.is_bot:
            self.users.add(user.id, user.full_name or "", user.username or "")
            current_user_id.set(user.id)
        # Нажата кнопка главного меню посреди другого раздела (например, начал
        # «Черный ящик», а потом нажал «Отсутствие») — бросаем начатое, чтобы кнопка
        # открыла свой раздел, а не попала в ответы прошлого.
        message = getattr(event, "message", None)
        state = data.get("state")
        if (
            message is not None and state is not None
            and message.text in MAIN_BUTTONS and message.text != BTN_CANCEL
            and await state.get_state() is not None
        ):
            await state.clear()
            data["raw_state"] = None  # фильтры состояний смотрят сюда
        return await handler(event, data)
