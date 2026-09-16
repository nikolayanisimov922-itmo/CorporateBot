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


@router.message(F.text == kb.BTN_SEND_DATA)
async def on_send_data(message: Message) -> None:
    await message.answer(
        "📤 <b>Передать данные</b>\n\n"
        "Здесь можно будет отправить заявку, показания или обратную связь — "
        "они попадут в таблицу.\n\n"
        "⏳ Пока это заглушка — сделаем на этапе 7."
    )


@router.message(F.text == kb.BTN_BROADCAST)
async def on_broadcast(message: Message, config: Config) -> None:
    # Дополнительная защита: кнопки нет в меню у обычных пользователей,
    # но если кто-то введёт текст вручную — тоже не пропускаем.
    if not config.is_admin(message.from_user.id):
        return
    await message.answer(
        "📢 <b>Рассылка</b> (только для администратора)\n\n"
        "Отсюда можно будет отправить объявление всем пользователям бота.\n\n"
        "⏳ Пока это заглушка — сделаем на этапе 6."
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
    text += "\nКоманда <code>/start</code> — открыть меню заново."
    await message.answer(text, reply_markup=kb.main_menu(is_admin))


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
