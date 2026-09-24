"""Настройки бота.

Все ключи читаются из файла .env (см. .env.example).
Один файл настроек на весь проект — как в плане.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    """Читает переменную окружения и убирает случайные пробелы по краям."""
    return os.getenv(name, default).strip()


def _int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ids(value: str) -> list[int]:
    """Разбирает список Telegram ID из строки «123, 456 789»."""
    out: list[int] = []
    for part in value.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                pass
    return out


@dataclass
class Config:
    # --- Этап 1: нужно уже сейчас ---
    bot_token: str
    admin_id: int
    # Ник администратора в Telegram (без @) — для контакта в разделе «Помощь».
    support_username: str = ""

    # --- Этап 4: Claude (понадобится позже) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"

    # --- Этап 2: Notion (понадобится позже) ---
    notion_token: str = ""
    notion_root_page: str = ""
    # Домен опубликованного сайта Notion (напр. mirror-psychology-ae8.notion.site).
    # Если задан — бот даёт публичные ссылки, которые открываются у всех.
    notion_public_domain: str = ""

    # --- Этап 6: получатели адресных рассылок {имя переменной .env -> [ID]} ---
    broadcast_ids: dict = field(default_factory=dict)

    # --- Этап 5: автообновление базы (минуты; 0 — выключено) ---
    refresh_interval_min: int = 60

    # --- Этап 7: Google Sheets ---
    # sheet_ids: {имя переменной из .env -> ID таблицы}. Своя таблица на каждую форму.
    sheet_ids: dict = field(default_factory=dict)
    google_credentials_file: str = "google_credentials.json"

    def is_admin(self, user_id: int) -> bool:
        """True только для владельца бота (по числовому Telegram ID)."""
        return self.admin_id != 0 and user_id == self.admin_id


def load_config() -> Config:
    token = _get("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN не задан.\n"
            "Скопируйте .env.example в .env (команда: cp .env.example .env) "
            "и впишите токен бота из @BotFather."
        )

    admin_raw = _get("ADMIN_ID", "0") or "0"
    try:
        admin_id = int(admin_raw)
    except ValueError:
        raise RuntimeError(
            "ADMIN_ID должен быть числом (узнать свой ID: напишите @userinfobot)."
        )

    # Собираем ID таблиц по формам: каждая форма знает имя своей переменной .env.
    from app.forms import FORMS

    sheet_ids: dict[str, str] = {}
    for form in FORMS.values():
        env_name = form.get("sheet_env")
        if env_name:
            value = _get(env_name)
            if value:
                sheet_ids[env_name] = value

    # Отдельная таблица для «Договорённости с клиентом».
    for env_name in ("GOOGLE_SHEET_AGREEMENTS",):
        value = _get(env_name)
        if value:
            sheet_ids[env_name] = value

    # Списки получателей адресных рассылок по пресетам.
    from app.broadcasts import PRESETS

    broadcast_ids: dict[str, list] = {}
    for preset in PRESETS.values():
        env_name = preset.get("ids_env")
        if env_name:
            ids = _ids(_get(env_name))
            if ids:
                broadcast_ids[env_name] = ids

    return Config(
        bot_token=token,
        admin_id=admin_id,
        support_username=_get("SUPPORT_USERNAME").lstrip("@"),
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        anthropic_model=_get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
        notion_token=_get("NOTION_TOKEN"),
        notion_root_page=_get("NOTION_ROOT_PAGE"),
        notion_public_domain=_get("NOTION_PUBLIC_DOMAIN"),
        broadcast_ids=broadcast_ids,
        refresh_interval_min=_int(_get("REFRESH_INTERVAL_MIN", "60"), 60),
        sheet_ids=sheet_ids,
        google_credentials_file=_get(
            "GOOGLE_CREDENTIALS_FILE", "google_credentials.json"
        ),
    )
