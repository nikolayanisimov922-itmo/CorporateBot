"""Сервис знаний: держит поиск+Claude и умеет обновлять базу «на лету» (этап 5).

Один объект живёт всё время работы бота. Кнопка «Обновить базу» и планировщик
вызывают refresh(): перечитать Notion → перестроить индекс → заменить его внутри
этого же объекта, чтобы бот сразу отвечал по свежим данным.
"""
from __future__ import annotations

import logging

from app.claude_answer import ClaudeAnswerer
from app.notion_loader import NotionLoader, write_knowledge_base
from app.rag import KB_FILE, Embedder, SearchIndex, build_chunks


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

    def refresh(self) -> tuple[int, int]:
        """Перечитывает Notion и перестраивает индекс. Блокирующая операция.

        Возвращает (число страниц, число кусков). Вызывать через asyncio.to_thread.
        """
        if not self.config.notion_token:
            raise RuntimeError("NOTION_TOKEN не задан в .env")

        logging.info("Обновление базы: читаю Notion...")
        loader = NotionLoader(self.config.notion_token, self.config.notion_root_page or "")
        pages = loader.load_all_shared()
        write_knowledge_base(pages, self.config.notion_root_page or "", KB_FILE)

        logging.info("Обновление базы: строю индекс...")
        chunks = build_chunks()
        if self.embedder is None:
            self.embedder = Embedder()
        new_index = SearchIndex.build(chunks, self.embedder)
        new_index.save()

        self.index = new_index  # горячая замена
        logging.info("База обновлена: %d страниц, %d кусков.", len(pages), len(chunks))
        return len(pages), len(chunks)
