"""Сборка всех роутеров бота в один."""
from aiogram import Router

from app.handlers import knowledge, menu


def setup_routers() -> Router:
    router = Router()
    # Роутер знаний — раньше меню: в режиме вопроса он перехватывает сообщения.
    router.include_router(knowledge.router)
    router.include_router(menu.router)
    return router
