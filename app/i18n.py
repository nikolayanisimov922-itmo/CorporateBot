"""Двуязычные тексты интерфейса (русский/английский).

t("ключ", lang) возвращает строку на нужном языке (по умолчанию — русский).
"""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "greeting": {
        "ru": (
            "Привет! Я корпоративный бот компании 🤖\n\n"
            "Помогу найти информацию в базе знаний, принять данные "
            "и держать вас в курсе новостей.\n\n"
            "Выберите раздел в меню ниже 👇"
        ),
        "en": (
            "Hi! I'm the company assistant bot 🤖\n\n"
            "I'll help you find information in the knowledge base, submit data "
            "and stay up to date.\n\n"
            "Choose a section in the menu below 👇"
        ),
    },
    "lang_switched": {
        "ru": "Язык переключён на русский 🇷🇺",
        "en": "Language switched to English 🇬🇧",
    },
    "fallback": {
        "ru": "Выберите раздел в меню ниже 👇",
        "en": "Please choose a section in the menu below 👇",
    },
    # --- Помощь ---
    "help_title": {"ru": "ℹ️ <b>Помощь</b>", "en": "ℹ️ <b>Help</b>"},
    "help_kb": {
        "ru": "📚 <b>База знаний</b> — задать вопрос по базе компании.",
        "en": "📚 <b>Knowledge base</b> — ask a question about the company base.",
    },
    "help_submit": {
        "ru": "📤 <b>Передать данные</b> — отправить выработку или планы.",
        "en": "📤 <b>Submit data</b> — send your output or plans.",
    },
    "help_lang": {
        "ru": "🌐 <b>English / Русский</b> — переключить язык бота.",
        "en": "🌐 <b>English / Русский</b> — switch the bot language.",
    },
    "help_admin_broadcast": {
        "ru": "📢 <b>Рассылка</b> — отправить объявление всем (видно только вам).",
        "en": "📢 <b>Broadcast</b> — send an announcement to everyone (admin only).",
    },
    "help_admin_refresh": {
        "ru": "🔄 <b>Обновить базу</b> — перечитать Notion прямо сейчас.",
        "en": "🔄 <b>Refresh base</b> — re-read Notion right now.",
    },
    "help_start_note": {
        "ru": "Команда <code>/start</code> — открыть меню заново.",
        "en": "Command <code>/start</code> — open the menu again.",
    },
    "help_contact": {
        "ru": (
            "🛠 <b>Нашли ошибку или хотите добавить функцию в бота?</b>\n"
            'Напишите Николаю: <a href="https://t.me/{user}">@{user}</a>'
        ),
        "en": (
            "🛠 <b>Found a bug or want a new feature?</b>\n"
            'Message Nikolay: <a href="https://t.me/{user}">@{user}</a>'
        ),
    },
    # --- База знаний ---
    "kb_enter": {
        "ru": (
            "📚 <b>База знаний</b>\n\n"
            "Задайте вопрос — найду ответ в базе компании и дам ссылку на источник.\n\n"
            "Чтобы вернуться в меню — кнопка «⬅️ Выйти в меню»."
        ),
        "en": (
            "📚 <b>Knowledge base</b>\n\n"
            "Ask a question — I'll find the answer in the company base and give a source link.\n\n"
            "To go back — the «⬅️ Back to menu» button."
        ),
    },
    "kb_exit": {
        "ru": "Вышли из базы знаний.",
        "en": "Exited the knowledge base.",
    },
    "kb_not_ready": {
        "ru": "⚠️ Поисковый индекс не готов. Сообщите администратору.",
        "en": "⚠️ The search index is not ready. Please contact the administrator.",
    },
    "kb_no_key": {
        "ru": "⚠️ ИИ временно недоступен. Сообщите администратору.",
        "en": "⚠️ The AI is temporarily unavailable. Please contact the administrator.",
    },
    "kb_error": {
        "ru": "😕 Не получилось получить ответ. Попробуйте ещё раз чуть позже.",
        "en": "😕 Couldn't get an answer. Please try again a bit later.",
    },
    "kb_no_info": {
        "ru": (
            "В базе знаний нет информации по вашему вопросу. "
            "Попробуйте переформулировать или уточните у руководителя."
        ),
        "en": (
            "There is no information on your question in the knowledge base. "
            "Try rephrasing it or ask your manager."
        ),
    },
    # --- Передать данные ---
    "submit_enter": {
        "ru": "📤 <b>Передать данные</b>\n\nВыберите, что хотите отправить:",
        "en": "📤 <b>Submit data</b>\n\nChoose what you want to send:",
    },
    "submit_choose_hint": {
        "ru": "Пожалуйста, выберите тип кнопкой ниже.",
        "en": "Please choose a type using the buttons below.",
    },
    "submit_saved": {
        "ru": "✅ Готово! Ваша запись сохранена. Спасибо!",
        "en": "✅ Done! Your entry has been saved. Thank you!",
    },
    "submit_error": {
        "ru": "❌ Не получилось сохранить. Попробуйте позже или сообщите администратору.",
        "en": "❌ Couldn't save. Please try later or contact the administrator.",
    },
    "submit_not_configured": {
        "ru": "⚠️ Приём данных пока не настроен. Загляните позже.",
        "en": "⚠️ Data submission is not set up yet. Please check back later.",
    },
    "cancelled": {"ru": "Отменено.", "en": "Cancelled."},
    # --- Договорённости с клиентом ---
    "agr_ask_project": {
        "ru": "Введите номер проекта в формате <b>123-45</b> (3 цифры – дефис – 2 цифры):",
        "en": "Enter the project number in the format <b>123-45</b> (3 digits – dash – 2 digits):",
    },
    "agr_bad_project": {
        "ru": "Неверный формат. Нужно 3 цифры, дефис, 2 цифры — например 123-45. Попробуйте ещё раз:",
        "en": "Wrong format. Need 3 digits, a dash, 2 digits — e.g. 123-45. Try again:",
    },
    "agr_ask_voice": {
        "ru": (
            "Супер, что у вас состоялась встреча с клиентом! 🎙\n\n"
            "Зафиксируйте ключевые договорённости <b>голосовым сообщением</b>."
        ),
        "en": (
            "Great that you had a meeting with the client! 🎙\n\n"
            "Record the key agreements as a <b>voice message</b>."
        ),
    },
    "agr_need_voice": {
        "ru": "Пожалуйста, отправьте именно <b>голосовое сообщение</b> (или нажмите «Отмена»).",
        "en": "Please send a <b>voice message</b> (or press «Cancel»).",
    },
    "agr_processing": {
        "ru": "Обрабатываю запись, это займёт минуту… ⏳",
        "en": "Processing your recording, it will take a minute… ⏳",
    },
    "agr_saved": {
        "ru": "✅ Готово, всё зафиксировано!",
        "en": "✅ Done, everything is recorded!",
    },
    "agr_error": {
        "ru": "❌ Не получилось сохранить. Попробуйте записать голосовое ещё раз.",
        "en": "❌ Couldn't save. Please try recording the voice message again.",
    },
    "agr_not_configured": {
        "ru": "⚠️ Функция пока не настроена. Сообщите администратору.",
        "en": "⚠️ This feature is not set up yet. Please contact the administrator.",
    },
}


def t(key: str, lang: str = "ru") -> str:
    entry = TEXTS.get(key, {})
    return entry.get(lang) or entry.get("ru") or key
