"""Этап 1: команда /start, главное меню и заглушки разделов.

Каждая кнопка пока отвечает пояснением — «наполним» на следующих этапах.
"""
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app import keyboards as kb
from config import Config

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, config: Config) -> None:
    is_admin = config.is_admin(message.from_user.id)
    await message.answer(
        "Привет! Я корпоративный бот компании 🤖\n\n"
        "Помогу найти информацию в базе знаний, принять данные "
        "и держать вас в курсе новостей.\n\n"
        "Выберите раздел в меню ниже 👇",
        reply_markup=kb.main_menu(is_admin),
    )


@router.message(F.text == kb.BTN_HELP)
async def on_help(message: Message, config: Config) -> None:
    is_admin = config.is_admin(message.from_user.id)
    text = (
        "ℹ️ <b>Помощь</b>\n\n"
        "📚 <b>База знаний</b> — задать вопрос по базе компании.\n"
        "📤 <b>Передать данные</b> — отправить заявку или обратную связь.\n"
    )
    if is_admin:
        text += "📢 <b>Рассылка</b> — отправить объявление всем (видно только вам).\n"
        text += "🔄 <b>Обновить базу</b> — перечитать Notion прямо сейчас.\n"
    text += "\nКоманда <code>/start</code> — открыть меню заново."

    if config.support_username:
        user = config.support_username
        text += (
            "\n\n🛠 <b>Нашли ошибку или хотите добавить функцию в бота?</b>\n"
            f"Напишите Николаю: <a href=\"https://t.me/{user}\">@{user}</a>"
        )

    await message.answer(
        text, reply_markup=kb.main_menu(is_admin), disable_web_page_preview=True
    )


@router.message()
async def fallback(message: Message, config: Config) -> None:
    """Любое непонятное сообщение — вежливо возвращаем в меню.

    На следующих этапах здесь появятся режимы (вопрос к базе, ввод данных),
    и этот обработчик будет срабатывать только вне режимов.
    """
    is_admin = config.is_admin(message.from_user.id)
    await message.answer(
        "Выберите раздел в меню ниже 👇",
        reply_markup=kb.main_menu(is_admin),
    )
