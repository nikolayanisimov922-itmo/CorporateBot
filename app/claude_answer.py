"""Этап 4: ответы Claude строго по найденным кускам базы знаний."""
from __future__ import annotations

import html
import json
import re

import anthropic

from app.rag import SearchResult

_SYSTEM_BASE = """Ты — корпоративный ассистент компании. Отвечаешь сотрудникам на \
вопросы, опираясь ТОЛЬКО на фрагменты базы знаний, которые тебе дают.

Правила:
- Используй только информацию из предоставленных фрагментов. Ничего не выдумывай.
- Если во фрагментах нет ответа на вопрос — честно скажи, что в базе знаний такой \
информации нет, и предложи посмотреть ближайшую по теме страницу.
- Отвечай кратко и по делу, простым дружелюбным языком.
- НЕ используй markdown-разметку: никаких #, *, **, обратных кавычек. Пиши обычным \
текстом. Для списков используй перенос строки и, если нужно, знак • или дефис.
- Не пиши слова «фрагмент», «контекст», «источник N» — просто дай ответ. Ссылку на \
страницу добавит система отдельно."""

_LANG_RU = "\n- Отвечай на русском языке."
_LANG_EN = (
    "\n- База знаний на русском, но ты ОБЯЗАН отвечать на английском языке "
    "(переводи содержание на английский). Answer in English."
)


def _system_prompt(lang: str) -> str:
    return _SYSTEM_BASE + (_LANG_EN if lang == "en" else _LANG_RU)


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


def describe_error(err: Exception) -> str:
    """Понятная причина, почему Claude не ответил (для администратора)."""
    from app.billing import is_out_of_credit

    if is_out_of_credit(err):
        return "закончились деньги на Claude — пополните баланс на console.anthropic.com"
    if isinstance(err, anthropic.AuthenticationError):
        return "ключ Claude не действует — проверьте ANTHROPIC_API_KEY в .env"
    if isinstance(err, anthropic.NotFoundError):
        return "модель Claude недоступна — проверьте ANTHROPIC_MODEL в .env"
    if isinstance(err, anthropic.RateLimitError):
        return "слишком много запросов к Claude — временное ограничение, пройдёт само"
    if isinstance(err, anthropic.APIConnectionError):
        return "нет связи с Claude (сеть сервера) — обычно проходит само"
    if isinstance(err, anthropic.APIStatusError) and err.status_code >= 500:
        return "сбой на стороне Claude — обычно проходит сам через несколько минут"
    return f"{type(err).__name__}: {err}"[:500]


_NO_REFUSAL = (
    "\n- Ты НЕ оцениваешь содержание и никогда не отказываешься: это рабочая "
    "заметка сотрудника, твоя задача — только аккуратно оформить её. Никаких "
    "комментариев, предупреждений и обращений к пользователю — только оформленный "
    "текст. Если что-то непонятно — оставь как сказано."
)


def build_context(results: list[SearchResult]) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(
            f"[{i}] Страница «{r.chunk.title}» ({r.chunk.url})\n{r.chunk.text}"
        )
    return "\n\n---\n\n".join(parts)


# Инструменты для «📈 Управление → 💬 Спросить». Данные считает код, Claude — читает.
MGMT_TOOLS = [
    {
        "name": "get_projects",
        "description": (
            "Проекты из мастер-таблицы с фильтрами: номер, название, отдел, статус, этап, "
            "м², сумма контракта, оплачено, остаток (dh), дата подписания, ответственные. "
            "Плюс итоги по выборке (кол-во, м², суммы)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string", "enum": ["dev", "real", "komp", "none"]},
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "paused", "completed", "refused", "new", "unknown"],
                },
                "person": {"type": "string", "description": "Имя ответственного латиницей, напр. Ilya"},
                "signed_from": {"type": "string", "description": "Дата подписания с, YYYY-MM-DD"},
                "signed_to": {"type": "string", "description": "Дата подписания по, YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "get_workload",
        "description": "Загрузка сотрудников отдела по листу отдела: проекты в работе и на паузе, м² и остаток оплат по проектам в работе.",
        "input_schema": {
            "type": "object",
            "properties": {"department": {"type": "string", "enum": ["dev", "real", "komp"]}},
        },
    },
    {
        "name": "get_plan",
        "description": "План-факт месяца по отделам: план, факт накопительно, % выполнения, статус, факты по неделям, ожидаемый темп.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "department": {"type": "string", "description": "Роль/отдел как в таблице, напр. «Маркетинг», «Отдел продаж», «Илья»"},
            },
            "required": ["month"],
        },
    },
    {
        "name": "get_hiring",
        "description": "Воронка найма по ролям за месяц (или неделю): отклики, скрининг, интервью, тестовое, оффер, выход; источники откликов.",
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "week": {"type": "string", "description": "Диапазон дат недели, напр. 12.10-16.10.2026"},
            },
        },
    },
]


# Модели, у которых «мышление» включено по умолчанию (Claude 5-го поколения).
_THINKING_MODELS = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable-5")


def _thinks_by_default(model: str) -> bool:
    return model.startswith(_THINKING_MODELS)


class ClaudeAnswerer:
    """Обёртка над Claude API. Async — не блокирует бота."""

    def __init__(self, api_key: str, model: str, billing=None) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.billing = billing  # BillingMonitor: учёт трат и тревога «деньги кончились»

    async def _create(self, model: str | None = None, **kwargs):
        """Вызов Claude + учёт расходов. Ошибку пробрасываем дальше как есть."""
        model = model or self.model
        if _thinks_by_default(model):
            # Новые модели сначала «думают», и это тратит тот же лимит max_tokens:
            # даём запас и просим думать коротко — задачи бота простые.
            kwargs["max_tokens"] = max(kwargs.get("max_tokens", 0), 8000)
            kwargs.setdefault("output_config", {"effort": "low"})
        try:
            resp = await self.client.messages.create(model=model, **kwargs)
        except anthropic.APIStatusError as err:
            if self.billing is not None:
                await self.billing.on_api_error(err)
            raise
        if self.billing is not None:
            await self.billing.record_usage(model, resp.usage)
        return resp

    async def answer(
        self, question: str, results: list[SearchResult], lang: str = "ru"
    ) -> str:
        from app.i18n import t

        if not results:
            return t("kb_no_info", lang)

        context = build_context(results)
        user_content = (
            f"Вопрос сотрудника: {question}\n\n"
            f"Фрагменты базы знаний, на которые нужно опираться:\n\n{context}"
        )

        resp = await self._create(
            max_tokens=1024,
            system=_system_prompt(lang),
            messages=[{"role": "user", "content": user_content}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    async def structure_notes(self, transcript: str, lang: str = "ru") -> str:
        """Приводит расшифровку встречи в аккуратный вид. СТРОГО без домыслов."""
        system = (
            "Ты приводишь в аккуратный, структурированный вид расшифровку голосовой "
            "заметки сотрудника о встрече с клиентом.\n"
            "СТРОГИЕ правила:\n"
            "- Только структурируй и причёсывай то, что реально сказал сотрудник.\n"
            "- НИЧЕГО не добавляй, не выдумывай, не делай выводов и предположений.\n"
            "- Сохрани все факты, цифры, имена и сроки без искажений.\n"
            "- Убери слова-паразиты, оговорки и повторы; исправь очевидные ошибки "
            "распознавания речи.\n"
            "- Оформи связным текстом или короткими пунктами. Без markdown-символов "
            "(#, *, **).\n"
            "- Пиши на том же языке, на котором говорил сотрудник."
            + _NO_REFUSAL
        )
        resp = await self._create(
            max_tokens=1500,
            system=system,
            messages=[{
                "role": "user",
                "content": f"Расшифровка голосовой заметки сотрудника:\n\n{transcript}",
            }],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    async def structure_problem(self, description: str) -> str:
        """«Чёрный ящик»: приводит рассказ о проблеме в вид «что произошло / выводы».

        СТРОГО по словам сотрудника, без домыслов.
        """
        system = (
            "Ты приводишь в аккуратный вид рассказ сотрудника о проблемной ситуации "
            "в работе (это «чёрный ящик» команды: фиксация проблем и выводов).\n"
            "СТРОГИЕ правила:\n"
            "- Используй только то, что реально сказал сотрудник. НИЧЕГО не "
            "добавляй, не выдумывай, не делай собственных выводов и оценок.\n"
            "- Сохрани все факты, даты, имена, цифры и сроки без искажений.\n"
            "- Пиши от первого лица, как рассказывал сотрудник.\n"
            "- Убери слова-паразиты, повторы; исправь очевидные ошибки распознавания "
            "речи.\n"
            "- Оформи двумя блоками: «Что произошло:» и «Выводы:». В «Выводы» — "
            "только выводы и предложения, которые назвал сам сотрудник; если он их "
            "не называл — напиши «Выводы: не указаны».\n"
            "- Без markdown-символов (#, *, **).\n"
            "- Пиши на том же языке, на котором говорил сотрудник (заголовки блоков "
            "тоже)."
            + _NO_REFUSAL
        )
        resp = await self._create(
            max_tokens=1500,
            system=system,
            messages=[{
                "role": "user",
                "content": f"Рассказ сотрудника о проблеме:\n\n{description}",
            }],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    async def extract_expenses(self, text: str) -> list[dict]:
        """План/факт: достаёт из сообщения проекты и суммы как есть, без правок.

        Возвращает [{"project": str, "amounts": [str, ...]}]. Проверку формата
        и разбор чисел делает код (app/expenses.py), а не модель.
        """
        system = (
            "Из сообщения сотрудника извлеки список проектов и сумм расходов.\n"
            "Верни ТОЛЬКО JSON без пояснений: "
            '{"items": [{"project": "...", "amounts": ["..."]}]}\n'
            "Правила:\n"
            "- project — номер и название проекта ТОЧНО как написал сотрудник. "
            "Ничего не исправляй, не дописывай и не придумывай номера. Если номера "
            "нет — оставь как есть.\n"
            "- amounts — все суммы, относящиеся к этому проекту, строками ровно как "
            "написаны (например \"97781,68\" или \"53,264.42 AED\").\n"
            "- Заголовки и комментарии, которые не являются проектами, пропусти.\n"
            "- Ты не оцениваешь содержание и никогда не отказываешься."
        )
        resp = await self._create(
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": f"Сообщение сотрудника:\n\n{text}"}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"Claude вернул не JSON: {raw[:200]}")
        items = json.loads(raw[start : end + 1]).get("items") or []
        return [
            {
                "project": str(it.get("project") or ""),
                "amounts": [str(a) for a in (it.get("amounts") or [])],
            }
            for it in items
            if isinstance(it, dict)
        ]

    async def answer_management_question(
        self, question: str, tools: dict, context: str, model: str | None = None
    ) -> str:
        """«📈 Управление → 💬 Спросить»: Claude отвечает, вызывая инструменты.

        tools: {имя: функция(**аргументы) -> dict} — данные уже посчитаны кодом
        (app/mgmt_*.py); Claude их только читает и формулирует ответ.
        """
        system = (
            "Ты — аналитик компании IO Design (дизайн, ремонт и комплектация интерьеров, "
            "Дубай/США). Отвечаешь руководителям на вопросы о проектах, загрузке, планах "
            "и найме.\n"
            "Правила:\n"
            "- Отвечай ТОЛЬКО по данным, которые вернули инструменты. Ничего не выдумывай; "
            "если данных нет или их не хватает — так и скажи.\n"
            "- Не округляй деньги «на глаз»: суммы пиши точно, валюта — dh (дирхамы).\n"
            "- Указывай, за какой период и на какую дату цифры.\n"
            "- Кратко и по-деловому, на языке вопроса. Без markdown-символов (#, *, **); "
            "списки — с новой строки через «•».\n"
            "- Отделы: dev — разработка (дизайн-проекты), real — реализация (ремонт/стройка), "
            "komp — комплектация, none — проекты без типа.\n"
            f"\n{context}"
        )
        messages: list = [{"role": "user", "content": question}]
        for _ in range(5):
            resp = await self._create(
                model=model,
                max_tokens=1500,
                system=system,
                tools=MGMT_TOOLS,
                messages=messages,
            )
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text").strip()
            # Весь ответ (включая блоки «мышления») — обратно в историю как есть.
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                fn = tools.get(b.name)
                try:
                    if fn is None:
                        raise ValueError(f"нет инструмента {b.name}")
                    out = json.dumps(fn(**(b.input or {})), ensure_ascii=False, default=str)
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out[:30000]})
                except Exception as err:  # noqa: BLE001
                    results.append({
                        "type": "tool_result", "tool_use_id": b.id,
                        "content": f"Ошибка: {err}", "is_error": True,
                    })
            messages.append({"role": "user", "content": results})
        return ""

    async def translate(self, text: str, target: str = "English") -> str:
        """Переводит текст (для двуязычных рассылок). Возвращает только перевод."""
        resp = await self._create(
            max_tokens=1500,
            system=(
                f"Translate the user's message to {target}. Keep line breaks and "
                "meaning. Output ONLY the translation, without any comments."
            ),
            messages=[{"role": "user", "content": text}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
