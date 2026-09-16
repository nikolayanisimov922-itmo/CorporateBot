"""Сборка всех роутеров бота в один."""
from aiogram import Router

from app.handlers import menu


def setup_routers() -> Router:
    router = Router()
    router.include_router(menu.router)
    return router
