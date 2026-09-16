"""Клавиатуры и главное меню бота."""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Тексты кнопок. Используются и для отрисовки меню, и для распознавания нажатий.
BTN_KNOWLEDGE = "📚 База знаний"
BTN_SEND_DATA = "📤 Передать данные"
BTN_BROADCAST = "📢 Рассылка"
BTN_REFRESH = "🔄 Обновить базу"
BTN_HELP = "ℹ️ Помощь"
BTN_EXIT = "⬅️ Выйти в меню"


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню.

    Кнопка «Рассылка» показывается только администратору (владельцу бота).
    """
    rows = [
        [KeyboardButton(text=BTN_KNOWLEDGE)],
        [KeyboardButton(text=BTN_SEND_DATA)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_BROADCAST)])
        rows.append([KeyboardButton(text=BTN_REFRESH)])
    rows.append([KeyboardButton(text=BTN_HELP)])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел…",
    )


def knowledge_menu() -> ReplyKeyboardMarkup:
    """Клавиатура режима «База знаний»: только кнопка выхода."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_EXIT)]],
        resize_keyboard=True,
        input_field_placeholder="Задайте вопрос по базе…",
    )
