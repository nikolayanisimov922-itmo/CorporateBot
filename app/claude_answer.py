"""Этап 4: ответы Claude строго по найденным кускам базы знаний."""
from __future__ import annotations

import anthropic

from app.rag import SearchResult

SYSTEM_PROMPT = """Ты — корпоративный ассистент компании. Отвечаешь сотрудникам на \
вопросы, опираясь ТОЛЬКО на фрагменты базы знаний, которые тебе дают.

Правила:
- Используй только информацию из предоставленных фрагментов. Ничего не выдумывай.
- Если во фрагментах нет ответа на вопрос — честно скажи, что в базе знаний такой \
информации нет, и предложи посмотреть ближайшую по теме страницу.
- Отвечай кратко и по делу, простым дружелюбным языком, на русском.
- Не пиши слова «фрагмент», «контекст», «источник N» — просто дай ответ. Ссылку на \
страницу добавит система отдельно."""


def build_context(results: list[SearchResult]) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(
            f"[{i}] Страница «{r.chunk.title}» ({r.chunk.url})\n{r.chunk.text}"
        )
    return "\n\n---\n\n".join(parts)


class ClaudeAnswerer:
    """Обёртка над Claude API. Async — не блокирует бота."""

    def __init__(self, api_key: str, model: str) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def answer(self, question: str, results: list[SearchResult]) -> str:
        if not results:
            return (
                "В базе знаний нет информации по вашему вопросу. "
                "Попробуйте переформулировать или уточнить у руководителя."
            )

        context = build_context(results)
        user_content = (
            f"Вопрос сотрудника: {question}\n\n"
            f"Фрагменты базы знаний, на которые нужно опираться:\n\n{context}"
        )

        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
