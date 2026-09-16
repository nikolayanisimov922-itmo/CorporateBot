"""Этап 3: отладочный режим поиска по базе (без ответа Claude).

Запуск:  python search_cli.py

Вводите вопрос — скрипт покажет заголовки страниц-источников, откуда
возьмётся ответ, и короткие фрагменты. Так проверяем, что поиск релевантный.
Выход: пустая строка, «exit» или Ctrl+C.
"""
from app.rag import Embedder, SearchIndex


def main() -> None:
    try:
        index = SearchIndex.load()
    except FileNotFoundError as err:
        print(f"❌ {err}")
        return

    print("Загружаю поисковую модель...")
    embedder = Embedder()
    print("\nГотово. Задавайте вопросы (пустая строка или «exit» — выход).\n")

    while True:
        try:
            query = input("Вопрос: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query or query.lower() in {"exit", "quit", "выход"}:
            break

        results = index.search(embedder, query, top_k=5)
        print("\nИсточники (по убыванию релевантности):")
        seen_titles = []
        for r in results:
            snippet = r.chunk.text.replace("\n", " ")[:160]
            marker = "★" if r.score >= 0.85 else " "
            print(f"  {marker} [{r.score:.2f}] {r.chunk.title}")
            print(f"        {snippet}…")
            if r.chunk.title not in seen_titles:
                seen_titles.append(r.chunk.title)
        print(f"\nСтраницы-источники: {', '.join(seen_titles)}\n")


if __name__ == "__main__":
    main()
