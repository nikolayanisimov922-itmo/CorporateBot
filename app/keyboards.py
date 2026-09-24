"""Клавиатуры и главное меню бота."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Тексты кнопок — двуязычные, чтобы работали для всех независимо от языка.
BTN_KNOWLEDGE = "📚 База знаний / Knowledge base"
BTN_SEND_DATA = "📤 Передать данные / Submit data"
BTN_AGREEMENTS = "🤝 Договорённости / Client notes"
BTN_BROADCAST = "📢 Рассылка / Broadcast"
BTN_REFRESH = "🔄 Обновить базу / Refresh"
BTN_HELP = "ℹ️ Помощь / Help"
BTN_LANG = "🌐 English / Русский"
BTN_EXIT = "⬅️ Выйти в меню / Back to menu"
BTN_CANCEL = "❌ Отмена / Cancel"

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
        [KeyboardButton(text=BTN_AGREEMENTS)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_BROADCAST)])
        rows.append([KeyboardButton(text=BTN_REFRESH)])
    rows.append([KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_LANG)])

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


def submit_menu(sheet_ids: dict) -> ReplyKeyboardMarkup:
    """Клавиатура выбора типа данных (этап 7).

    Показываем только те формы, для которых настроена таблица (есть ID в .env).
    """
    from app.forms import FORMS

    rows = [
        [KeyboardButton(text=form["title"])]
        for form in FORMS.values()
        if form["sheet_env"] in sheet_ids
    ]
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите тип данных…",
    )


def broadcast_menu() -> ReplyKeyboardMarkup:
    """Меню выбора типа рассылки (общая + пресеты по группам)."""
    from app.broadcasts import GENERAL_TITLE, PRESETS

    rows = [[KeyboardButton(text=GENERAL_TITLE)]]
    for preset in PRESETS.values():
        rows.append([KeyboardButton(text=preset["title"])])
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите тип рассылки…",
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
