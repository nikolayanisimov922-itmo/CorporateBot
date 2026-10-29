"""Раздел «📈 Управление» — сводки для руководителей по живым Google-таблицам.

Доступ — по Telegram ID (MGMT_IDS) + админ. Проверка в КАЖДОМ обработчике:
кнопку в меню видят только руководители, но колбэк мог бы прислать кто угодно.

Итерация 1: меню, /myid, /mgmt_ping (проверка доступа ко всем таблицам и листам).
Разделы «Проекты», «Планы», «HR», «Спросить» подключаются следующими итерациями.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app import keyboards as kb
from app.expenses import now_dubai
from app.management_data import SheetCache, ping
from app.sheets import SheetsClient
from app.users import UserRegistry
from config import Config

router = Router()

CB = "mg"  # mg:<раздел>

TXT = {
    "menu": {
        "ru": "📈 <b>Управление</b>\n\nВыберите раздел:",
        "en": "📈 <b>Management</b>\n\nChoose a section:",
    },
    "soon": {
        "ru": "🚧 Этот раздел подключаю — скоро здесь будут цифры из таблиц.",
        "en": "🚧 This section is being connected — figures from the tables are coming soon.",
    },
    "refreshed": {
        "ru": "🔄 Кэш сброшен — следующий запрос прочитает таблицы заново.",
        "en": "🔄 Cache cleared — the next request will re-read the tables.",
    },
}
BUTTONS = [
    ("projects", "📁 Проекты / Projects"),
    ("plan", "📊 Планы / Plans"),
    ("hr", "👥 HR"),
    ("ask", "💬 Спросить / Ask"),
    ("refresh", "🔄 Обновить данные / Refresh"),
]


def _tx(key: str, lang: str) -> str:
    return TXT[key]["en" if lang == "en" else "ru"]


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=title, callback_data=f"{CB}:{key}")]
        for key, title in BUTTONS
    ])


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀ Назад / Back", callback_data=f"{CB}:menu")
    ]])


@router.message(Command("myid"))
async def my_id(message: Message) -> None:
    """Показывает Telegram ID — чтобы собрать ID руководителей для MGMT_IDS."""
    await message.answer(
        f"Ваш Telegram ID / Your Telegram ID: <code>{message.from_user.id}</code>"
    )


@router.message(F.text == kb.BTN_MGMT)
async def open_menu(message: Message, config: Config, users: UserRegistry) -> None:
    if not config.is_mgmt(message.from_user.id):
        return
    lang = users.get_lang(message.from_user.id)
    await message.answer(_tx("menu", lang), reply_markup=_menu_kb())


@router.callback_query(F.data.startswith(f"{CB}:"))
async def on_section(
    callback: CallbackQuery, config: Config, users: UserRegistry, mgmt_cache: SheetCache
) -> None:
    if not config.is_mgmt(callback.from_user.id):
        await callback.answer()
        return
    lang = users.get_lang(callback.from_user.id)
    section = callback.data.split(":", 1)[1]
    if section == "menu":
        await callback.answer()
        await callback.message.edit_text(_tx("menu", lang), reply_markup=_menu_kb())
        return
    if section == "refresh":
        mgmt_cache.clear()
        await callback.answer(_tx("refreshed", lang), show_alert=False)
        return
    await callback.answer()
    await callback.message.edit_text(_tx("soon", lang), reply_markup=_back_kb())


@router.message(Command("mgmt_ping"))
async def mgmt_ping(message: Message, config: Config, sheets: SheetsClient | None) -> None:
    """Админ: видит ли бот все три таблицы и все нужные листы."""
    if not config.is_admin(message.from_user.id):
        return
    if sheets is None:
        await message.answer("❌ Google Sheets не подключены (нет google_credentials.json).")
        return
    await message.answer("🔎 Проверяю доступ к таблицам…")
    try:
        lines = await asyncio.to_thread(
            ping, sheets, config.mgmt_sheet_ids, now_dubai().date()
        )
    except Exception:  # noqa: BLE001
        logging.exception("Управление: ошибка /mgmt_ping")
        await message.answer("❌ Проверка упала с ошибкой — подробности в логах.")
        return
    lines = ["🔎 <b>Доступ к таблицам «Управления»</b>", ""] + lines
    lines.append(f"Почта бота: <code>{sheets.email}</code>")
    # Режем по строкам, чтобы не разорвать HTML-теги (лимит Telegram 4096).
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            await message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await message.answer(chunk)
