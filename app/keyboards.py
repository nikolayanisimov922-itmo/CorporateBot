"""Клавиатуры и главное меню бота."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Тексты кнопок. Используются и для отрисовки меню, и для распознавания нажатий.
BTN_KNOWLEDGE = "📚 База знаний"
BTN_SEND_DATA = "📤 Передать данные"
BTN_BROADCAST = "📢 Рассылка"
BTN_REFRESH = "🔄 Обновить базу"
BTN_HELP = "ℹ️ Помощь"
BTN_EXIT = "⬅️ Выйти в меню"
BTN_CANCEL = "❌ Отмена"

# callback_data для подтверждения рассылки
CB_BROADCAST_SEND = "bcast_send"
CB_BROADCAST_CANCEL = "bcast_cancel"


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


def cancel_menu(placeholder: str = "Введите текст…") -> ReplyKeyboardMarkup:
    """Клавиатура с одной кнопкой «Отмена»."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
        input_field_placeholder=placeholder,
    )


def submit_menu() -> ReplyKeyboardMarkup:
    """Клавиатура выбора типа данных (этап 7). Строится из FORMS."""
    from app.forms import FORMS

    rows = [[KeyboardButton(text=form["title"])] for form in FORMS.values()]
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите тип данных…",
    )


def broadcast_confirm() -> InlineKeyboardMarkup:
    """Кнопки подтверждения рассылки под предпросмотром."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отправить всем", callback_data=CB_BROADCAST_SEND
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=CB_BROADCAST_CANCEL
                ),
            ]
        ]
    )
