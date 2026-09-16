"""Точка входа корпоративного бота.

Запуск локально:  python bot.py
Работает на «длинных опросах» (long polling) — публичный адрес не нужен.
Пока окно терминала открыто — бот отвечает. Закрыли — бот «спит».
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.claude_answer import ClaudeAnswerer
from app.handlers import setup_routers
from app.rag import Embedder, SearchIndex
from config import load_config


def load_knowledge(config):
    """Загружает поисковый индекс, модель и клиента Claude (этапы 3–4).

    Возвращает (index, embedder, answerer). Любой элемент может быть None,
    если что-то ещё не готово — бот всё равно запустится (меню работает).
    """
    index = embedder = answerer = None
    try:
        index = SearchIndex.load()
        embedder = Embedder()
        logging.info("Поисковый индекс загружен: %d кусков.", len(index.chunks))
    except FileNotFoundError:
        logging.warning(
            "Индекс не найден — раздел «База знаний» недоступен. "
            "Постройте: python build_index.py"
        )

    if config.anthropic_api_key:
        answerer = ClaudeAnswerer(config.anthropic_api_key, config.anthropic_model)
        logging.info("Claude подключён (модель %s).", config.anthropic_model)
    else:
        logging.warning("ANTHROPIC_API_KEY не задан — ответы Claude недоступны.")

    return index, embedder, answerer


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    config = load_config()
    index, embedder, answerer = load_knowledge(config)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(setup_routers())

    me = await bot.get_me()
    logging.info("Бот запущен: @%s. Напишите ему /start в Telegram.", me.username)

    # Сбрасываем возможный старый вебхук и накопившиеся апдейты.
    await bot.delete_webhook(drop_pending_updates=True)

    # Зависимости прокидываются во все обработчики по имени аргумента.
    await dp.start_polling(
        bot,
        config=config,
        index=index,
        embedder=embedder,
        answerer=answerer,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
