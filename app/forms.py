"""Этап 7: описания форм приёма данных.

Каждая форма пишет в СВОЮ Google-таблицу (у каждой свой ID в .env — sheet_env).
Чтобы добавить новый тип данных — допишите запись в FORMS и новую строку в .env.

Поля формы:
  key       — внутренний идентификатор
  title     — текст кнопки и заголовок
  sheet_env — имя переменной в .env, где лежит ID нужной Google-таблицы
  worksheet — название листа внутри таблицы
  fields    — шаги опроса: key (столбец), label (заголовок), q (вопрос)
"""
from __future__ import annotations

FORMS: dict[str, dict] = {
    "vyrabotka": {
        "key": "vyrabotka",
        "title": "📊 Выработка",
        "sheet_env": "GOOGLE_SHEET_VYRABOTKA",
        "worksheet": "Выработка",
        "fields": [
            {
                "key": "project",
                "label": "Проект/объект",
                "q": "По какому проекту или объекту выработка?",
            },
            {"key": "work", "label": "Что сделано", "q": "Что сделано (какие работы)?"},
            {
                "key": "amount",
                "label": "Объём/количество",
                "q": "Объём или количество (напр. «120 м²» или «3 шт»):",
            },
        ],
    },
    "plany": {
        "key": "plany",
        "title": "🗓 Планы",
        "sheet_env": "GOOGLE_SHEET_PLANY",
        "worksheet": "Планы",
        "fields": [
            {
                "key": "project",
                "label": "Проект/направление",
                "q": "По какому проекту или направлению план?",
            },
            {"key": "plan", "label": "План", "q": "Что планируется сделать?"},
            {"key": "deadline", "label": "Срок", "q": "К какому сроку? (напр. «до 25.09»)"},
        ],
    },
}


def form_by_title(title: str) -> dict | None:
    for form in FORMS.values():
        if form["title"] == title:
            return form
    return None
