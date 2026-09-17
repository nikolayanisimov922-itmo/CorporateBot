"""Этап 7: описания форм приёма данных.

Чтобы добавить новый тип данных — допишите запись в FORMS. Каждая форма:
  key    — внутренний идентификатор
  title  — текст кнопки и заголовок
  sheet  — название листа в Google-таблице, куда падают строки
  fields — список шагов опроса: key (столбец), label (заголовок), q (вопрос)
"""
from __future__ import annotations

FORMS: dict[str, dict] = {
    "request": {
        "key": "request",
        "title": "📋 Заявка",
        "sheet": "Заявки",
        "fields": [
            {"key": "subject", "label": "Тема", "q": "Кратко: что нужно? (тема заявки)"},
            {
                "key": "details",
                "label": "Подробности",
                "q": "Подробности (или «-», если добавить нечего):",
            },
        ],
    },
    "meter": {
        "key": "meter",
        "title": "🔢 Показания",
        "sheet": "Показания",
        "fields": [
            {
                "key": "meter",
                "label": "Счётчик",
                "q": "Какой счётчик/показатель? (напр. «электричество»)",
            },
            {"key": "value", "label": "Значение", "q": "Введите значение:"},
        ],
    },
    "feedback": {
        "key": "feedback",
        "title": "💬 Обратная связь",
        "sheet": "Обратная связь",
        "fields": [
            {"key": "message", "label": "Сообщение", "q": "Напишите вашу обратную связь:"},
        ],
    },
}


def form_by_title(title: str) -> dict | None:
    for form in FORMS.values():
        if form["title"] == title:
            return form
    return None
