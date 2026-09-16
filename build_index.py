"""Этап 3: построение поискового индекса из выгруженной базы знаний.

Запуск:  python build_index.py

Берёт data/knowledge_base.json, режет на куски, кодирует локальной моделью
и сохраняет индекс в data/. При первом запуске скачает модель (~470 МБ) — это
один раз; дальше работает офлайн.
"""
from app.rag import KB_FILE, Embedder, SearchIndex, build_chunks


def main() -> None:
    if not KB_FILE.exists():
        print(
            "❌ Нет файла с базой знаний (data/knowledge_base.json).\n"
            "   Сначала выгрузите базу: python sync_notion.py"
        )
        return

    print("Режу базу на куски...")
    chunks = build_chunks()
    if not chunks:
        print("❌ В базе нет текста для индексации.")
        return
    pages = len({c.page_id for c in chunks})
    print(f"Получилось {len(chunks)} кусков из {pages} страниц.\n")

    print("Загружаю поисковую модель (при первом запуске — скачивание ~470 МБ)...")
    embedder = Embedder()

    print("Строю индекс (кодирую куски)...")
    index = SearchIndex.build(chunks, embedder)
    index.save()

    print(f"\n✅ Индекс построен: {len(chunks)} кусков из {pages} страниц.")
    print("   Проверьте поиск: python search_cli.py")


if __name__ == "__main__":
    main()
