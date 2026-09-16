"""Сервис знаний: держит поиск+Claude и умеет обновлять базу «на лету» (этап 5).

Один объект живёт всё время работы бота. Кнопка «Обновить базу» и планировщик
вызывают refresh(): перечитать Notion → перестроить индекс → заменить его внутри
этого же объекта, чтобы бот сразу отвечал по свежим данным.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.claude_answer import ClaudeAnswerer
from app.notion_loader import NotionLoader, write_knowledge_base
from app.rag import KB_FILE, Embedder, SearchIndex, build_chunks


@dataclass
class RefreshResult:
    pages: int  # всего страниц в базе сейчас
    chunks: int  # всего кусков сейчас
    added: int  # новых страниц
    updated: int  # изменённых страниц
    removed: int  # удалённых страниц

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


class KnowledgeService:
    def __init__(
        self,
        config,
        index: SearchIndex | None,
        embedder: Embedder | None,
        answerer: ClaudeAnswerer | None,
    ) -> None:
        self.config = config
        self.index = index
        self.embedder = embedder
        self.answerer = answerer

    @property
    def ready(self) -> bool:
        return self.index is not None and self.embedder is not None

    def search(self, query: str, top_k: int):
        return self.index.search(self.embedder, query, top_k)

    @staticmethod
    def _old_page_map() -> dict[str, str]:
        """Прежнее содержимое базы {id страницы: текст} — чтобы сравнить изменения."""
        if not KB_FILE.exists():
            return {}
        try:
            data = json.loads(KB_FILE.read_text(encoding="utf-8"))
            return {p["id"]: p.get("text", "") for p in data.get("pages", [])}
        except (json.JSONDecodeError, OSError, KeyError):
            return {}

    def refresh(self) -> RefreshResult:
        """Перечитывает Notion и перестраивает индекс. Блокирующая операция.

        Возвращает RefreshResult с общими числами и дельтой (что изменилось).
        Вызывать через asyncio.to_thread.
        """
        if not self.config.notion_token:
            raise RuntimeError("NOTION_TOKEN не задан в .env")

        old = self._old_page_map()

        logging.info("Обновление базы: читаю Notion...")
        loader = NotionLoader(self.config.notion_token, self.config.notion_root_page or "")
        pages = loader.load_all_shared()
        new = {p.id: p.text for p in pages}

        added = sum(1 for pid in new if pid not in old)
        removed = sum(1 for pid in old if pid not in new)
        updated = sum(1 for pid in new if pid in old and new[pid] != old[pid])

        write_knowledge_base(pages, self.config.notion_root_page or "", KB_FILE)

        logging.info("Обновление базы: строю индекс...")
        chunks = build_chunks()
        if self.embedder is None:
            self.embedder = Embedder()
        new_index = SearchIndex.build(chunks, self.embedder)
        new_index.save()

        self.index = new_index  # горячая замена
        result = RefreshResult(
            pages=len(pages),
            chunks=len(chunks),
            added=added,
            updated=updated,
            removed=removed,
        )
        logging.info(
            "База обновлена: %d страниц (+%d новых, ~%d изменённых, -%d удалённых).",
            result.pages, result.added, result.updated, result.removed,
        )
        return result
