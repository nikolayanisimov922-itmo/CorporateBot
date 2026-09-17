"""Сборка всех роутеров бота в один."""
from aiogram import Router

from app.handlers import broadcast, knowledge, menu, submit


def setup_routers() -> Router:
    router = Router()
    # Роутеры с FSM-состояниями — раньше меню: в своём режиме они
    # перехватывают сообщения, а fallback меню их не трогает.
    router.include_router(knowledge.router)
    router.include_router(broadcast.router)
    router.include_router(submit.router)
    router.include_router(menu.router)
    return router
