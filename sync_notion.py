"""Этап 2: команда выгрузки базы знаний из Notion.

Запуск:  python sync_notion.py

Читает всю базу из Notion и сохраняет её в data/knowledge_base.json.
В конце печатает «Загружено N страниц» — сверьте число со своей базой в Notion.
"""
import datetime as dt
import json
import pathlib

from app.notion_loader import NotionLoader, page_to_dict
from config import load_config

DATA_FILE = pathlib.Path("data") / "knowledge_base.json"


def main() -> None:
    cfg = load_config()

    if not cfg.notion_token or not cfg.notion_root_page:
        print(
            "❌ Не заданы NOTION_TOKEN и/или NOTION_ROOT_PAGE в файле .env.\n"
            "   Заполните их (см. инструкцию в SETUP.md, раздел «Этап 2») и повторите."
        )
        return

    print("Читаю базу знаний из Notion...\n")
    loader = NotionLoader(cfg.notion_token, cfg.notion_root_page)
    try:
        pages = loader.load()
    except Exception as err:  # noqa: BLE001 — показываем пользователю понятную причину
        print(f"\n❌ Ошибка при чтении Notion: {err}")
        print(
            "   Частые причины: интеграция не подключена к головной странице "
            "(••• → Connections), неверный токен или ссылка."
        )
        return

    DATA_FILE.parent.mkdir(exist_ok=True)
    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "root_page": cfg.notion_root_page,
        "pages_count": len(pages),
        "pages": [page_to_dict(p) for p in pages],
    }
    DATA_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total_chars = sum(p.chars for p in pages)
    print(f"\n✅ Загружено {len(pages)} страниц ({total_chars:,} символов).".replace(",", " "))
    print(f"   Сохранено в {DATA_FILE}")
    print("   Сверьте число страниц со своей базой в Notion.")


if __name__ == "__main__":
    main()
