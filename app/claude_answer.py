"""Этап 4: ответы Claude строго по найденным кускам базы знаний."""
from __future__ import annotations

import html
import re

import anthropic

from app.rag import SearchResult

SYSTEM_PROMPT = """Ты — корпоративный ассистент компании. Отвечаешь сотрудникам на \
вопросы, опираясь ТОЛЬКО на фрагменты базы знаний, которые тебе дают.

Правила:
- Используй только информацию из предоставленных фрагментов. Ничего не выдумывай.
- Если во фрагментах нет ответа на вопрос — честно скажи, что в базе знаний такой \
информации нет, и предложи посмотреть ближайшую по теме страницу.
- Отвечай кратко и по делу, простым дружелюбным языком, на русском.
- НЕ используй markdown-разметку: никаких #, *, **, обратных кавычек. Пиши обычным \
текстом. Для списков используй перенос строки и, если нужно, знак • или дефис.
- Не пиши слова «фрагмент», «контекст», «источник N» — просто дай ответ. Ссылку на \
страницу добавит система отдельно."""


def render_markdown(raw: str) -> str:
    """Превращает остатки markdown в аккуратный текст для Telegram (HTML).

    Заголовки (#) → жирный текст, **жирный** → жирный, списки → «•»,
    лишние символы * и # убираются.
    """
    text = html.escape(raw)

    # **жирный** и __жирный__ → настоящий жирный
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    out_lines = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        header = re.match(r"#{1,6}\s+(.*)", stripped)
        if header:
            out_lines.append(f"{indent}<b>{header.group(1).strip()}</b>")
            continue

        bullet = re.match(r"[-*•]\s+(.*)", stripped)
        if bullet:
            out_lines.append(f"{indent}• {bullet.group(1)}")
            continue

        out_lines.append(line)

    text = "\n".join(out_lines)

    # Убираем оставшиеся одиночные * (курсив) и любые лишние # / *
    text = re.sub(r"\*(\S[^*\n]*?\S|\S)\*", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    return text.strip()


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
