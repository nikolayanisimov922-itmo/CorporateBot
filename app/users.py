"""Этап 6: реестр пользователей бота.

Бот запоминает каждого, кто хоть раз им воспользовался (нажал /start или
написал сообщение). Список хранится в data/users.json и используется для рассылок.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

USERS_FILE = pathlib.Path("data") / "users.json"


class UserRegistry:
    def __init__(self) -> None:
        self._users: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if USERS_FILE.exists():
            try:
                data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
                self._users = data.get("users", {})
            except (json.JSONDecodeError, OSError):
                self._users = {}

    def _save(self) -> None:
        USERS_FILE.parent.mkdir(exist_ok=True)
        USERS_FILE.write_text(
            json.dumps({"users": self._users}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, user_id: int, name: str = "", username: str = "") -> None:
        """Запоминает пользователя (или обновляет имя, если менялось)."""
        key = str(user_id)
        existing = self._users.get(key)
        if existing is None:
            self._users[key] = {
                "name": name,
                "username": username,
                "first_seen": dt.datetime.now().isoformat(timespec="seconds"),
            }
            self._save()
        elif existing.get("name") != name or existing.get("username") != username:
            existing["name"] = name
            existing["username"] = username
            self._save()

    def all_ids(self) -> list[int]:
        return [int(k) for k in self._users]

    def count(self) -> int:
        return len(self._users)
