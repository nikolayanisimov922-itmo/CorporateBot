"""Служебные сообщения администратору в личку."""
from __future__ import annotations

import logging


async def alert_admin(bot, config, header: str, body: str = "") -> bool:
    """Шлёт админу заголовок (HTML) и, если есть, текст без разметки частями.

    Возвращает True, если всё доставлено.
    """
    if not config.admin_id:
        return False
    try:
        await bot.send_message(config.admin_id, header, disable_web_page_preview=True)
        for i in range(0, len(body), 4000):  # лимит Telegram — 4096 символов
            await bot.send_message(config.admin_id, body[i : i + 4000], parse_mode=None)
        return True
    except Exception:  # noqa: BLE001
        logging.exception("Не удалось отправить сообщение админу")
        return False
