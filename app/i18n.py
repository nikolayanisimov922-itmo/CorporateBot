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
        "ru": "📤 <b>Передать данные</b> — план и факт расходов (комплектаторы и ПМ).",
        "en": "📤 <b>Submit data</b> — planned and actual expenses (procurement and PMs).",
    },
    "help_blackbox": {
        "ru": "⬛ <b>Черный ящик</b> — сразу зафиксировать проблему или сложный кейс.",
        "en": "⬛ <b>Black box</b> — record a problem or a difficult case right away.",
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
    "help_admin_balance": {
        "ru": "💰 <b>Баланс</b> — сколько денег осталось на Claude; сюда же вводить сумму после пополнения.",
        "en": "💰 <b>Balance</b> — Claude credit left; enter the new amount here after a top-up.",
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
        "ru": "Какой проект? (можно номер или название)",
        "en": "Which project? (number or name)",
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
    "agr_saved_backup": {
        "ru": "✅ Готово! Договорённость получена и передана руководителю.",
        "en": "✅ Done! The notes have been received and passed to the manager.",
    },
    "agr_error": {
        "ru": "❌ Не получилось сохранить. Попробуйте записать голосовое ещё раз.",
        "en": "❌ Couldn't save. Please try recording the voice message again.",
    },
    "agr_not_configured": {
        "ru": "⚠️ Функция пока не настроена. Сообщите администратору.",
        "en": "⚠️ This feature is not set up yet. Please contact the administrator.",
    },
    # --- Черный ящик ---
    "bb_ask_department": {
        "ru": (
            "⬛ <b>Черный ящик</b>\n\n"
            "Здесь фиксируем проблемы и сложные кейсы — чтобы разобраться и не "
            "повторять.\n\nВыберите ваш отдел:"
        ),
        "en": (
            "⬛ <b>Black box</b>\n\n"
            "Here we record problems and difficult cases — to sort them out and "
            "not repeat them.\n\nChoose your department:"
        ),
    },
    "bb_pick_department": {
        "ru": "Пожалуйста, выберите отдел кнопкой ниже 👇",
        "en": "Please choose a department with the buttons below 👇",
    },
    "bb_ask_story": {
        "ru": (
            "Расскажите своими словами — <b>голосовым</b> или <b>текстом</b>, как удобно:\n\n"
            "• что произошло и когда;\n"
            "• что вы уже сделали;\n"
            "• какие выводы можно сделать, чтобы это не повторилось."
        ),
        "en": (
            "Tell us in your own words — by <b>voice</b> or <b>text</b>, as you prefer:\n\n"
            "• what happened and when;\n"
            "• what you have already done;\n"
            "• what conclusions can be drawn so it doesn't happen again."
        ),
    },
    "bb_need_story": {
        "ru": "Пришлите голосовое или текст (или нажмите «Отмена»).",
        "en": "Please send a voice message or text (or press «Cancel»).",
    },
    "bb_ask_severity": {
        "ru": (
            "Насколько это серьёзно?\n\n"
            "🔴 <b>Критично</b> — реальные последствия для денег, репутации перед "
            "клиентом или срока сдачи проекта, либо повторяется не первый раз.\n"
            "🟠 <b>Средне</b> — заметная проблема, потребовала лишнего времени и нервов, "
            "но вы справились сами.\n"
            "🟢 <b>Незначительно</b> — небольшая шероховатость, для истории; реакция "
            "руководителя не нужна."
        ),
        "en": (
            "How serious is it?\n\n"
            "🔴 <b>Critical</b> — real consequences for money, reputation with the "
            "client or the project deadline, or it is not the first time.\n"
            "🟠 <b>Medium</b> — a noticeable problem that cost extra time and nerves, "
            "but you handled it yourself.\n"
            "🟢 <b>Minor</b> — a small hiccup, for the record; no manager reaction needed."
        ),
    },
    "bb_pick_severity": {
        "ru": "Пожалуйста, выберите вариант кнопкой ниже 👇",
        "en": "Please choose an option with the buttons below 👇",
    },
    "bb_saved": {
        "ru": "✅ Спасибо! Кейс записан в «Черный ящик».",
        "en": "✅ Thank you! The case is recorded in the «Black box».",
    },
    "bb_saved_backup": {
        "ru": "✅ Спасибо! Кейс получен и передан руководителю.",
        "en": "✅ Thank you! The case has been received and passed to the manager.",
    },
    "bb_voice_error": {
        "ru": "❌ Не получилось распознать голосовое. Запишите ещё раз или напишите текстом.",
        "en": "❌ Couldn't recognise the voice message. Please record again or type it.",
    },
}


def t(key: str, lang: str = "ru") -> str:
    entry = TEXTS.get(key, {})
    return entry.get(lang) or entry.get("ru") or key
