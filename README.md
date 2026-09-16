# CorporateBot 🤖

Корпоративный бот на **Claude (Anthropic)**: база знаний из Notion + поиск (RAG),
приём данных в Google Sheets и рассылки. Собираем локально, поэтапно; хостинг — последний шаг.

## Стек

| Деталь | Технология | Где работает |
|---|---|---|
| Движок бота | aiogram (Telegram) | локально |
| Чтение базы | Notion API | локально |
| Поиск (RAG) | локальная модель + мини-база | локально, бесплатно |
| Ответы | Claude (Anthropic) | облако (API оплачен) |
| Сбор данных | Google Sheets | облако |
| Хостинг | Railway / Render | этап 9 |

## Этапы

- [x] **0. Подготовка** — структура проекта, файл настроек
- [x] **1. Каркас бота** — `/start`, меню с кнопками (long polling)
- [x] **2. Notion** — выгрузка базы (`python sync_notion.py`) ← *мы здесь*
- [ ] 3. Поиск (RAG)
- [ ] 4. База знаний — ответы Claude
- [ ] 5. Актуальность — обновление базы
- [ ] 6. Рассылки
- [ ] 7. Приём данных → Google Sheets
- [ ] 8. Полная проверка
- [ ] 9. Хостинг 24/7

## Быстрый старт

Подробная инструкция для Mac — в файле **[SETUP.md](SETUP.md)**. Коротко:

```bash
git clone https://github.com/nikolayanisimov922-itmo/CorporateBot.git
cd CorporateBot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # затем впишите BOT_TOKEN и ADMIN_ID в .env
python bot.py
```

Пока `python bot.py` запущен и окно терминала открыто — бот отвечает.
Закрыли терминал — бот «спит» (круглосуточную работу включим на этапе 9).
