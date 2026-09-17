"""Этап 6+: типы рассылок.

Общая рассылка — всем пользователям, текст вводит админ.
Пресеты — конкретным группам (по списку ID из .env), с готовым текстом:
достаточно нажать кнопку и подтвердить.

Чтобы добавить новый тип: допишите запись в PRESETS и список ID в .env.
  key      — идентификатор
  title    — текст кнопки
  ids_env  — имя переменной .env со списком ID получателей (через запятую)
  message  — готовый текст рассылки
"""
from __future__ import annotations

GENERAL_TITLE = "📢 Общая рассылка"

PRESETS: dict[str, dict] = {
    "pm_friday": {
        "key": "pm_friday",
        "title": "👷 ПМ (пятница)",
        "ids_env": "PM_IDS",
        "message": (
            "Не забудьте передать клиенту план работ на следующую неделю "
            "и отчёт за эту неделю — передайте данные сегодня."
        ),
    },
    "komplekt_friday": {
        "key": "komplekt_friday",
        "title": "📦 Комплектаторы (пятница)",
        "ids_env": "KOMPLEKT_IDS",
        "message": (
            "🇷🇺 Не забудьте передать выработку сегодня.\n\n"
            "🇬🇧 Please remember to submit your output today."
        ),
    },
}


def preset_by_title(title: str) -> dict | None:
    for preset in PRESETS.values():
        if preset["title"] == title:
            return preset
    return None
