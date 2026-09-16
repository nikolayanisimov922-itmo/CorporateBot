"""Диагностика доступа Notion.

Запуск:  python notion_check.py

Спрашивает у Notion, какие страницы и базы видит ваша интеграция
(по токену из .env). Помогает понять, к чему реально открыт доступ,
и получить правильный ID/ссылку головной страницы.
"""
from notion_client import Client
from notion_client.errors import APIResponseError

from app.notion_loader import _rich_text
from config import load_config


def _title(obj: dict) -> str:
    """Заголовок страницы или базы данных из результата поиска."""
    if obj.get("object") == "database":
        return _rich_text(obj.get("title", [])) or "Без названия (база)"
    for prop in obj.get("properties", {}).values():
        if prop.get("type") == "title":
            t = _rich_text(prop.get("title", []))
            if t.strip():
                return t.strip()
    return "Без названия"


def main() -> None:
    cfg = load_config()
    if not cfg.notion_token:
        print("❌ NOTION_TOKEN не задан в .env")
        return

    tail = cfg.notion_token[-4:]
    print(f"Токен из .env: ...{tail} (последние 4 символа)")
    print("Спрашиваю Notion, что видит эта интеграция...\n")

    client = Client(auth=cfg.notion_token)
    try:
        resp = client.search(page_size=100)
    except APIResponseError as err:
        print(f"❌ Ошибка запроса: {err}")
        print("   Скорее всего, токен неверный или неполный.")
        return

    results = resp.get("results", [])
    if not results:
        print("⚠️  Интеграция НЕ видит НИ ОДНОЙ страницы.\n")
        print("Это значит одно из двух:")
        print("  • токен в .env принадлежит ДРУГОЙ интеграции (возможно, у вас")
        print("    их две с именем CorporateBot — проверьте notion.so/my-integrations);")
        print("  • либо подключение на странице сделано к другой интеграции.\n")
        print("Что сделать: откройте notion.so/my-integrations, выберите интеграцию,")
        print("которую подключили к странице (Active connections → CorporateBot),")
        print("скопируйте ЕЁ токен (Show → Copy) и вставьте в .env как NOTION_TOKEN.")
        return

    print(f"✅ Интеграция видит объектов: {len(results)}\n")
    for r in results:
        kind = "БАЗА " if r.get("object") == "database" else "стр. "
        print(f"  [{kind}] {_title(r)}")
        print(f"           id:  {r.get('id')}")
        print(f"           url: {r.get('url', '—')}")
    print(
        "\nНайдите в списке «Ivan Ogienko - Knowledge Base» — это головная страница.\n"
        "Скопируйте её url (строка выше) в .env как NOTION_ROOT_PAGE и запустите\n"
        "python sync_notion.py заново."
    )


if __name__ == "__main__":
    main()
