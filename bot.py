"""Точка входа корпоративного бота.

Запуск локально:  python bot.py
Работает на «длинных опросах» (long polling) — публичный адрес не нужен.
Пока окно терминала открыто — бот отвечает. Закрыли — бот «спит».
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.claude_answer import ClaudeAnswerer
from app.handlers import setup_routers
from app.knowledge_service import KnowledgeService
from app.middlewares import RegisterUserMiddleware
from app.rag import Embedder, SearchIndex
from app.sheets import SheetsClient
from app.users import UserRegistry
from config import load_config


def build_sheets(config) -> SheetsClient | None:
    """Подключает Google Sheets (этап 7). None, если не настроено."""
    if not config.google_sheet_id:
        logging.warning("GOOGLE_SHEET_ID не задан — раздел «Передать данные» недоступен.")
        return None
    if not os.path.exists(config.google_credentials_file):
        logging.warning(
            "Файл %s не найден — раздел «Передать данные» недоступен.",
            config.google_credentials_file,
        )
        return None
    try:
        client = SheetsClient(config.google_credentials_file, config.google_sheet_id)
        logging.info("Google Sheets подключены.")
        return client
    except Exception:  # noqa: BLE001
        logging.exception("Не удалось подключить Google Sheets")
        return None


def build_knowledge(config) -> KnowledgeService:
    """Собирает сервис знаний: индекс, модель поиска и клиент Claude (этапы 3–5).

    Любой элемент может быть None, если что-то ещё не готово — бот всё равно
    запустится (меню работает), а недоступные разделы вежливо об этом скажут.
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

    return KnowledgeService(config, index, embedder, answerer)


async def auto_refresh_loop(knowledge: KnowledgeService, interval_min: int) -> None:
    """Периодически перечитывает Notion (этап 5, «обновление по расписанию»)."""
    while True:
        await asyncio.sleep(interval_min * 60)
        try:
            res = await asyncio.to_thread(knowledge.refresh)
            logging.info(
                "Автообновление базы: %d страниц (+%d/~%d/-%d).",
                res.pages, res.added, res.updated, res.removed,
            )
        except Exception:  # noqa: BLE001
            logging.exception("Ошибка автообновления базы")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    config = load_config()
    knowledge = build_knowledge(config)
    sheets = build_sheets(config)
    users = UserRegistry()
    logging.info("Реестр пользователей: %d чел.", users.count())

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    # Запоминаем каждого, кто пишет боту (для рассылок).
    dp.update.outer_middleware(RegisterUserMiddleware(users))
    dp.include_router(setup_routers())

    me = await bot.get_me()
    logging.info("Бот запущен: @%s. Напишите ему /start в Telegram.", me.username)

    # Автообновление базы по расписанию (0 в .env — выключено).
    if config.refresh_interval_min > 0 and config.notion_token:
        asyncio.create_task(auto_refresh_loop(knowledge, config.refresh_interval_min))
        logging.info("Автообновление базы каждые %d мин.", config.refresh_interval_min)

    # Сбрасываем возможный старый вебхук и накопившиеся апдейты.
    await bot.delete_webhook(drop_pending_updates=True)

    # Зависимости прокидываются во все обработчики по имени аргумента.
    await dp.start_polling(
        bot, config=config, knowledge=knowledge, users=users, sheets=sheets
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
