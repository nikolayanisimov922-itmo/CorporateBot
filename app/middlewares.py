"""Middleware: запоминает каждого пользователя, который пишет боту (этап 6)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

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
        return await handler(event, data)
