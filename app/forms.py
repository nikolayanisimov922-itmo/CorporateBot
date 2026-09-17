"""Этап 7: описания форм приёма данных (двуязычные).

Каждая форма пишет в СВОЮ Google-таблицу (sheet_env — имя переменной .env с ID).
Заголовки колонок в таблице — на русском (их читает администратор).
Вопросы сотруднику показываются на его языке (q — рус, q_en — англ).
"""
from __future__ import annotations

FORMS: dict[str, dict] = {
    "vyrabotka": {
        "key": "vyrabotka",
        "title": "📊 Выработка / Output",
        "sheet_env": "GOOGLE_SHEET_VYRABOTKA",
        "worksheet": "Выработка",
        "fields": [
            {
                "key": "project",
                "label": "Проект/объект",
                "q": "По какому проекту или объекту выработка?",
                "q_en": "Which project or site is the output for?",
            },
            {
                "key": "work",
                "label": "Что сделано",
                "q": "Что сделано (какие работы)?",
                "q_en": "What was done (which works)?",
            },
            {
                "key": "amount",
                "label": "Объём/количество",
                "q": "Объём или количество (напр. «120 м²» или «3 шт»):",
                "q_en": "Volume or quantity (e.g. «120 m²» or «3 pcs»):",
            },
        ],
    },
    "plany": {
        "key": "plany",
        "title": "🗓 Планы / Plans",
        "sheet_env": "GOOGLE_SHEET_PLANY",
        "worksheet": "Планы",
        "fields": [
            {
                "key": "plan",
                "label": "Планы",
                "q": "Напишите ваши планы в свободном формате одним сообщением:",
                "q_en": "Write your plans in free form in one message:",
            },
        ],
    },
}


def form_by_title(title: str) -> dict | None:
    for form in FORMS.values():
        if form["title"] == title:
            return form
    return None


def field_question(field: dict, lang: str) -> str:
    if lang == "en" and field.get("q_en"):
        return field["q_en"]
    return field["q"]
