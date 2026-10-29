"""Клавиатуры и главное меню бота."""
from __future__ import annotations

import contextvars

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
BTN_BLACKBOX = "⬛ Черный ящик / Black box"
BTN_BROADCAST = "📢 Рассылка / Broadcast"
BTN_REFRESH = "🔄 Обновить базу / Refresh"
BTN_BALANCE = "💰 Баланс / Balance"
BTN_MGMT = "📈 Управление / Management"
BTN_HELP = "ℹ️ Помощь / Help"
BTN_LANG = "🌐 English / Русский"
BTN_EXIT = "⬅️ Выйти в меню / Back to menu"
BTN_CANCEL = "❌ Отмена / Cancel"

# callback_data для подтверждения рассылки
CB_BROADCAST_SEND = "bcast_send"
CB_BROADCAST_CANCEL = "bcast_cancel"


# Кто сейчас пользуется ботом — выставляет RegisterUserMiddleware на каждое
# сообщение. Нужно, чтобы кнопку «📈 Управление» видели только руководители,
# не передавая ID во все вызовы main_menu().
current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_user_id", default=None
)
_mgmt_ids: set[int] = set()


def set_mgmt_ids(ids) -> None:
    """Вызывается при старте бота: ID руководителей из MGMT_IDS."""
    _mgmt_ids.clear()
    _mgmt_ids.update(int(i) for i in ids)


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню.

    Кнопки «Рассылка» и др. — только администратору; «📈 Управление» —
    руководителям из MGMT_IDS и администратору.
    """
    rows = [
        [KeyboardButton(text=BTN_KNOWLEDGE)],
        [KeyboardButton(text=BTN_SEND_DATA)],
        [KeyboardButton(text=BTN_AGREEMENTS)],
        [KeyboardButton(text=BTN_BLACKBOX)],
    ]
    if is_admin or current_user_id.get() in _mgmt_ids:
        rows.append([KeyboardButton(text=BTN_MGMT)])
    if is_admin:
        rows.append([KeyboardButton(text=BTN_BROADCAST)])
        rows.append([KeyboardButton(text=BTN_REFRESH)])
        rows.append([KeyboardButton(text=BTN_BALANCE)])
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


def departments_menu() -> ReplyKeyboardMarkup:
    """«Чёрный ящик»: выбор отдела (по два в ряд)."""
    from app.blackbox import DEPARTMENTS

    buttons = [KeyboardButton(text=d) for d in DEPARTMENTS]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите отдел…",
    )


def severity_menu() -> ReplyKeyboardMarkup:
    """«Чёрный ящик»: серьёзность проблемы."""
    from app.blackbox import SEVERITIES

    rows = [[KeyboardButton(text=s)] for s in SEVERITIES]
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Насколько серьёзно?",
    )
