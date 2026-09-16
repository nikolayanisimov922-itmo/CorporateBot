"""Этап 3: локальный семантический поиск по базе знаний (RAG).

Режем страницы на куски, кодируем их локальной бесплатной моделью
(intfloat/multilingual-e5-small — хорошо понимает русский) и ищем по смыслу
через косинусную близость. Индекс лежит файлами в data/ рядом с ботом.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# Модель качаем один раз при первом запуске (~470 МБ), дальше работает офлайн.
MODEL_NAME = "intfloat/multilingual-e5-small"

DATA_DIR = pathlib.Path("data")
KB_FILE = DATA_DIR / "knowledge_base.json"
EMB_FILE = DATA_DIR / "index_embeddings.npy"
META_FILE = DATA_DIR / "index_meta.json"


# ---------------------------------------------------------------- нарезка
def chunk_page_text(text: str, max_chars: int = 800, overlap: int = 150) -> list[str]:
    """Режет текст страницы на куски по абзацам, с небольшим нахлёстом."""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 1 <= max_chars:
            cur = (cur + "\n" + p).strip()
            continue
        if cur:
            chunks.append(cur)
        if len(p) <= max_chars:
            # начинаем новый кусок с нахлёстом от предыдущего
            tail = cur[-overlap:] if cur else ""
            cur = (tail + "\n" + p).strip() if tail else p
        else:
            # очень длинный абзац — режем окном
            for i in range(0, len(p), max_chars - overlap):
                chunks.append(p[i : i + max_chars])
            cur = ""
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c.strip()]


@dataclass
class Chunk:
    page_id: str
    title: str
    url: str
    text: str


def build_chunks(kb_path: pathlib.Path = KB_FILE) -> list[Chunk]:
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    for page in data.get("pages", []):
        title = page.get("title", "Без названия")
        url = page.get("url", "")
        pid = page.get("id", "")
        body = page.get("text", "").strip()
        if not body:
            continue
        for piece in chunk_page_text(body):
            chunks.append(Chunk(page_id=pid, title=title, url=url, text=piece))
    return chunks


# ------------------------------------------------------------- модель/эмбеддинги
class Embedder:
    """Обёртка над локальной моделью. Загружается один раз."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(MODEL_NAME)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        # e5 требует префикс "passage:" для документов
        prefixed = [f"passage: {t}" for t in texts]
        return self.model.encode(
            prefixed,
            normalize_embeddings=True,
            show_progress_bar=True,
            batch_size=32,
        ).astype(np.float32)

    def encode_query(self, query: str) -> np.ndarray:
        # ...и "query:" для вопроса
        return self.model.encode(
            f"query: {query}", normalize_embeddings=True
        ).astype(np.float32)


# ------------------------------------------------------------------- индекс
@dataclass
class SearchResult:
    score: float
    chunk: Chunk


@dataclass
class SearchIndex:
    embeddings: np.ndarray
    chunks: list[Chunk]

    # --- построение и сохранение ---
    @classmethod
    def build(cls, chunks: list[Chunk], embedder: Embedder) -> "SearchIndex":
        vectors = embedder.encode_passages([c.text for c in chunks])
        return cls(embeddings=vectors, chunks=chunks)

    def save(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        np.save(EMB_FILE, self.embeddings)
        meta = {
            "model": MODEL_NAME,
            "chunks": [
                {"page_id": c.page_id, "title": c.title, "url": c.url, "text": c.text}
                for c in self.chunks
            ],
        }
        META_FILE.write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

    # --- загрузка ---
    @classmethod
    def load(cls) -> "SearchIndex":
        if not EMB_FILE.exists() or not META_FILE.exists():
            raise FileNotFoundError(
                "Индекс поиска не найден. Сначала постройте его: python build_index.py"
            )
        embeddings = np.load(EMB_FILE)
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))
        chunks = [
            Chunk(page_id=c["page_id"], title=c["title"], url=c["url"], text=c["text"])
            for c in meta["chunks"]
        ]
        return cls(embeddings=embeddings, chunks=chunks)

    # --- поиск ---
    def search(
        self, embedder: Embedder, query: str, top_k: int = 5
    ) -> list[SearchResult]:
        qv = embedder.encode_query(query)
        scores = self.embeddings @ qv  # косинус (векторы нормированы)
        top_idx = np.argsort(-scores)[:top_k]
        return [
            SearchResult(score=float(scores[i]), chunk=self.chunks[i])
            for i in top_idx
        ]
