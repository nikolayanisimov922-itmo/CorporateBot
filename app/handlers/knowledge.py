"""Этап 4: режим «База знаний» — Claude отвечает по базе + ссылка на Notion."""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app import keyboards as kb
from app.claude_answer import render_markdown
from app.knowledge_service import KnowledgeService
from config import Config

router = Router()

TOP_K = 6  # сколько кусков искать под вопрос


class KnowledgeStates(StatesGroup):
    asking = State()


@router.message(F.text == kb.BTN_KNOWLEDGE)
async def enter_knowledge(message: Message, state: FSMContext) -> None:
    await state.set_state(KnowledgeStates.asking)
    await message.answer(
        "📚 <b>База знаний</b>\n\n"
        "Задайте вопрос — найду ответ в базе компании и дам ссылку на источник.\n\n"
        "Чтобы вернуться в меню — кнопка «⬅️ Выйти в меню».",
        reply_markup=kb.knowledge_menu(),
    )


@router.message(KnowledgeStates.asking, F.text == kb.BTN_EXIT)
async def exit_knowledge(message: Message, state: FSMContext, config: Config) -> None:
    await state.clear()
    is_admin = config.is_admin(message.from_user.id)
    await message.answer("Вышли из базы знаний.", reply_markup=kb.main_menu(is_admin))


@router.message(KnowledgeStates.asking, F.text)
async def ask_question(message: Message, knowledge: KnowledgeService) -> None:
    # Проверки готовности (индекс построен, ключ Claude задан).
    if not knowledge.ready:
        await message.answer(
            "⚠️ Поисковый индекс не готов. Постройте его командой "
            "<code>python build_index.py</code> и перезапустите бота.",
            reply_markup=kb.knowledge_menu(),
        )
        return
    if knowledge.answerer is None:
        await message.answer(
            "⚠️ Не задан ключ Claude (ANTHROPIC_API_KEY в .env). "
            "Добавьте его и перезапустите бота.",
            reply_markup=kb.knowledge_menu(),
        )
        return

    question = message.text.strip()
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Поиск — в отдельном потоке, чтобы не блокировать бота.
        results = await asyncio.to_thread(knowledge.search, question, TOP_K)
        answer = await knowledge.answerer.answer(question, results)
    except Exception:  # noqa: BLE001
        logging.exception("Ошибка при ответе на вопрос")
        await message.answer(
            "😕 Не получилось получить ответ. Попробуйте ещё раз чуть позже.",
            reply_markup=kb.knowledge_menu(),
        )
        return

    # Ближайшие источники (до 2 уникальных страниц).
    sources: list[tuple[str, str]] = []
    for r in results:
        pair = (r.chunk.title, r.chunk.url)
        if r.chunk.url and pair not in sources:
            sources.append(pair)
        if len(sources) >= 2:
            break

    text = render_markdown(answer)
    if sources:
        links = " · ".join(
            f"<a href=\"{html.escape(url)}\">{html.escape(title)}</a>"
            for title, url in sources
        )
        text += f"\n\n🔗 {links}"

    await message.answer(
        text, reply_markup=kb.knowledge_menu(), disable_web_page_preview=True
    )


@router.message(F.text == kb.BTN_REFRESH)
async def refresh_base(
    message: Message, config: Config, knowledge: KnowledgeService
) -> None:
    """Кнопка «Обновить базу» — только для админа. Перечитывает Notion."""
    if not config.is_admin(message.from_user.id):
        return

    await message.answer("🔄 Обновляю базу из Notion, это займёт минуту…")
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        pages, chunks = await asyncio.to_thread(knowledge.refresh)
    except Exception as err:  # noqa: BLE001
        logging.exception("Ошибка обновления базы")
        await message.answer(
            f"❌ Не удалось обновить базу: {err}",
            reply_markup=kb.main_menu(is_admin=True),
        )
        return

    await message.answer(
        f"✅ База обновлена: {pages} страниц ({chunks} кусков).\n"
        "Можно задавать вопросы — бот уже учитывает свежие данные.",
        reply_markup=kb.main_menu(is_admin=True),
    )
