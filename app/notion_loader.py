"""Этап 2: выгрузка базы знаний из Notion.

Обходит головную страницу и все подстраницы (рекурсивно), превращает
их в текст и запоминает ссылку на каждую. Результат сохраняется локально
в data/knowledge_base.json, чтобы можно было убедиться, что всё на месте.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from notion_client import Client
from notion_client.errors import APIResponseError

# Типы блоков, у которых текст лежит в поле rich_text.
_TEXT_BLOCKS = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
    "code",
}

# Красивые префиксы, чтобы итоговый текст читался структурно.
_PREFIX = {
    "heading_1": "# ",
    "heading_2": "## ",
    "heading_3": "### ",
    "bulleted_list_item": "• ",
    "numbered_list_item": "- ",
    "quote": "> ",
}


def extract_page_id(raw: str) -> str:
    """Из ссылки или сырого ID достаёт page_id в формате UUID с дефисами."""
    raw = raw.strip().split("?")[0]
    ids = re.findall(r"[0-9a-fA-F]{32}", raw.replace("-", ""))
    if not ids:
        raise ValueError(
            f"Не удалось распознать ID страницы Notion в значении: {raw!r}. "
            "Скопируйте ссылку на головную страницу целиком."
        )
    h = ids[-1].lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _rich_text(arr: list) -> str:
    return "".join(part.get("plain_text", "") for part in (arr or []))


@dataclass
class NotionPage:
    id: str
    title: str
    url: str
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass
class NotionLoader:
    token: str
    root_page: str
    _client: Client = field(init=False)
    _visited: set = field(init=False, default_factory=set)
    pages: list = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._client = Client(auth=self.token)

    # --- публичный вход ---
    def load(self) -> list[NotionPage]:
        root_id = extract_page_id(self.root_page)
        print(f"ID головной страницы: {root_id}")

        # Явно проверяем доступ к головной странице и даём понятную ошибку.
        try:
            self._client.pages.retrieve(page_id=root_id)
            is_database = False
        except APIResponseError as err:
            status = getattr(err, "status", None)
            if status == 401:
                raise RuntimeError(
                    "Токен Notion не принят (ошибка 401). Проверьте NOTION_TOKEN в .env: "
                    "он должен начинаться на ntn_ (или secret_) и быть скопирован ЦЕЛИКОМ, "
                    "без лишних пробелов и кавычек."
                ) from err
            if status == 404:
                # Возможно, головная — это база данных, а не страница. Проверим.
                try:
                    self._client.databases.retrieve(database_id=root_id)
                    is_database = True
                except APIResponseError:
                    raise RuntimeError(
                        "Нет доступа к головной странице (ошибка 404). Убедитесь, что:\n"
                        "   1) интеграция «CorporateBot» подключена ИМЕННО к головной "
                        "странице «Ivan Ogienko - Knowledge Base» (••• → на этой странице "
                        "→ поиск «connect» → Connections → CorporateBot);\n"
                        "   2) ссылка NOTION_ROOT_PAGE в .env ведёт на эту же страницу."
                    ) from err
            else:
                raise

        if is_database:
            self._load_database(root_id)
        else:
            self._load_page(root_id)
        return self.pages

    # --- загрузка всех страниц, доступных интеграции (через search) ---
    def load_all_shared(self) -> list[NotionPage]:
        """Берёт все страницы, к которым открыт доступ интеграции.

        Не требует ссылки на головную страницу: Notion сам отдаёт список
        всего, что «расшарено» на интеграцию (через endpoint search).
        """
        cursor: Optional[str] = None
        while True:
            resp = self._client.search(start_cursor=cursor, page_size=100)
            for obj in resp.get("results", []):
                if obj.get("object") == "page":
                    self._load_single_page(obj)
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
            time.sleep(0.2)  # бережём лимит Notion
        return self.pages

    def _load_single_page(self, meta: dict) -> None:
        page_id = meta["id"].replace("-", "")
        if page_id in self._visited:
            return
        self._visited.add(page_id)

        title = self._page_title(meta)
        url = meta.get("url") or f"https://www.notion.so/{page_id}"

        lines: list[str] = []
        skip: list[str] = []  # дочерние страницы придут отдельным элементом search
        try:
            self._read_blocks(page_id, lines, skip, skip)
        except APIResponseError as err:
            print(f"  ⚠ Пропускаю «{title}»: {err}")
            return

        text = "\n".join(line for line in lines if line.strip())
        self.pages.append(NotionPage(id=page_id, title=title, url=url, text=text))
        print(f"  ✓ {title} ({len(text)} симв.)")

    # --- обход одной страницы (по ссылке на головную — оставлено для этапа 5) ---
    def _load_page(self, page_id: str) -> None:
        page_id = page_id.replace("-", "")
        if page_id in self._visited:
            return
        self._visited.add(page_id)

        try:
            meta = self._client.pages.retrieve(page_id=page_id)
        except APIResponseError as err:
            print(f"  ⚠ Пропускаю страницу {page_id}: {err}")
            return

        title = self._page_title(meta)
        url = meta.get("url") or f"https://www.notion.so/{page_id}"

        lines: list[str] = []
        child_pages: list[str] = []
        child_dbs: list[str] = []
        self._read_blocks(page_id, lines, child_pages, child_dbs)

        text = "\n".join(line for line in lines if line.strip())
        self.pages.append(NotionPage(id=page_id, title=title, url=url, text=text))
        print(f"  ✓ {title} ({len(text)} симв.)")

        for cid in child_pages:
            self._load_page(cid)
        for db_id in child_dbs:
            self._load_database(db_id)

    # --- рекурсивное чтение блоков страницы ---
    def _read_blocks(
        self,
        block_id: str,
        lines: list,
        child_pages: list,
        child_dbs: list,
    ) -> None:
        cursor: Optional[str] = None
        while True:
            resp = self._client.blocks.children.list(
                block_id=block_id, start_cursor=cursor, page_size=100
            )
            for block in resp.get("results", []):
                self._handle_block(block, lines, child_pages, child_dbs)

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
            time.sleep(0.2)  # бережём лимит Notion (~3 запроса/сек)

    def _handle_block(
        self,
        block: dict,
        lines: list,
        child_pages: list,
        child_dbs: list,
    ) -> None:
        btype = block.get("type", "")

        if btype == "child_page":
            child_pages.append(block["id"])
            return
        if btype == "child_database":
            child_dbs.append(block["id"])
            return

        # Ссылка на другую страницу/базу (оглавление, «link to page»).
        if btype == "link_to_page":
            body = block.get("link_to_page", {})
            if body.get("type") == "page_id" and body.get("page_id"):
                child_pages.append(body["page_id"])
            elif body.get("type") == "database_id" and body.get("database_id"):
                child_dbs.append(body["database_id"])
            return

        # Ссылки-упоминания страниц внутри текстовых блоков (@страница).
        if btype in _TEXT_BLOCKS:
            for part in block.get(btype, {}).get("rich_text", []):
                mention = part.get("mention", {})
                if mention.get("type") == "page":
                    child_pages.append(mention["page"]["id"])
                elif mention.get("type") == "database":
                    child_dbs.append(mention["database"]["id"])

        if btype in _TEXT_BLOCKS:
            body = block.get(btype, {})
            txt = _rich_text(body.get("rich_text", []))
            if btype == "to_do":
                mark = "[x] " if body.get("checked") else "[ ] "
                txt = mark + txt
            elif btype in _PREFIX:
                txt = _PREFIX[btype] + txt
            if txt.strip():
                lines.append(txt)

        # Вложенные блоки (toggle, колонки, списки с подпунктами и т.п.)
        if block.get("has_children"):
            self._read_blocks(block["id"], lines, child_pages, child_dbs)

    # --- строки базы данных как отдельные страницы ---
    def _load_database(self, db_id: str) -> None:
        cursor: Optional[str] = None
        while True:
            try:
                resp = self._client.databases.query(
                    database_id=db_id, start_cursor=cursor, page_size=100
                )
            except APIResponseError as err:
                print(f"  ⚠ Пропускаю базу {db_id}: {err}")
                return
            for row in resp.get("results", []):
                self._load_page(row["id"])
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
            time.sleep(0.2)

    # --- заголовок страницы из её свойств ---
    @staticmethod
    def _page_title(meta: dict) -> str:
        props = meta.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                title = _rich_text(prop.get("title", []))
                if title.strip():
                    return title.strip()
        return "Без названия"


def page_to_dict(page: NotionPage) -> dict:
    d = asdict(page)
    d["chars"] = page.chars
    return d


def write_knowledge_base(pages: list[NotionPage], root_page: str, path) -> None:
    """Сохраняет выгруженные страницы в JSON (общий формат для sync и обновления)."""
    import datetime as _dt
    import json as _json
    import pathlib as _pathlib

    path = _pathlib.Path(path)
    path.parent.mkdir(exist_ok=True)
    payload = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "root_page": root_page,
        "pages_count": len(pages),
        "pages": [page_to_dict(p) for p in pages],
    }
    path.write_text(
        _json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
