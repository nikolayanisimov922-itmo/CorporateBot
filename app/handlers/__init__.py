"""Сборка всех роутеров бота в один."""
from aiogram import Router

from app.handlers import (
    agreements,
    billing,
    blackbox,
    broadcast,
    expenses,
    knowledge,
    management,
    menu,
)


def setup_routers() -> Router:
    router = Router()
    # Роутеры с FSM-состояниями — раньше меню: в своём режиме они
    # перехватывают сообщения, а fallback меню их не трогает.
    router.include_router(knowledge.router)
    router.include_router(broadcast.router)
    router.include_router(expenses.router)
    router.include_router(management.router)
    router.include_router(agreements.router)
    router.include_router(blackbox.router)
    router.include_router(billing.router)
    router.include_router(menu.router)
    return router
