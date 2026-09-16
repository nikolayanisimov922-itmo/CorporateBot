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

from app.handlers import setup_routers
from config import load_config


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    config = load_config()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(setup_routers())

    me = await bot.get_me()
    logging.info("Бот запущен: @%s. Напишите ему /start в Telegram.", me.username)

    # Сбрасываем возможный старый вебхук и накопившиеся апдейты.
    await bot.delete_webhook(drop_pending_updates=True)

    # config прокидывается во все обработчики как аргумент config.
    await dp.start_polling(bot, config=config)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
