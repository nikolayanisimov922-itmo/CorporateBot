"""Раздел «📈 Управление» — сводки для руководителей по живым Google-таблицам.

Доступ — по Telegram ID (MGMT_IDS) + админ. Проверка в КАЖДОМ обработчике:
кнопку в меню видят только руководители, но колбэк мог бы прислать кто угодно.

Цифры по кнопкам считает код (app/mgmt_*.py) — точно и без токенов. ИИ — только
в «💬 Спросить» (tool use: Claude вызывает функции, код возвращает готовые данные).
Навигация — inline-кнопки, одно сообщение редактируется (edit_text).
"""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app import keyboards as kb
from app import management_format as fm
from app.claude_answer import describe_error, render_markdown
from app.expenses import now_dubai
from app.knowledge_service import KnowledgeService
from app.management_data import (
    HIRING,
    MONTHS_EN,
    PLAN,
    PROJECTS,
    TABLE_TITLES,
    SheetCache,
    ping,
)
from app.mgmt_hiring import hiring_query, parse_hiring, roles
from app.mgmt_plan import parse_plans, plan_query
from app.mgmt_projects import DEPTS, parse_projects, people, query_projects
from app.notify import alert_admin
from app.sheets import SheetsClient
from app.transcribe import Transcriber, voice_to_text
from app.users import UserRegistry
from config import Config

router = Router()

CB = "mg"
MAX_LEN = 3900

TXT = {
    "menu": {"ru": "📈 <b>Управление</b>\n\nВыберите раздел:", "en": "📈 <b>Management</b>\n\nChoose a section:"},
    "refreshed": {"ru": "🔄 Данные будут прочитаны заново", "en": "🔄 Data will be re-read"},
    "fail": {
        "ru": "😕 Не удалось получить данные из таблицы «{t}». Админ уже знает.",
        "en": "😕 Couldn't get data from the «{t}» table. The admin has been notified.",
    },
    "not_set": {
        "ru": "⚙️ Таблица «{t}» ещё не подключена (нет ID в настройках).",
        "en": "⚙️ The «{t}» table isn't connected yet (no ID in settings).",
    },
    "projects": {"ru": "📁 <b>Проекты</b>\n\nЧто показать?", "en": "📁 <b>Projects</b>\n\nWhat to show?"},
    "choose_dept": {"ru": "Выберите отдел:", "en": "Choose a department:"},
    "ask": {
        "ru": (
            "💬 <b>Спросить</b>\n\nЗадайте вопрос текстом или голосовым по проектам, "
            "загрузке, планам или найму. Например: «сколько дизайн-проектов на паузе у Ильи "
            "и на какую сумму?»"
        ),
        "en": (
            "💬 <b>Ask</b>\n\nAsk a question by text or voice about projects, workload, plans "
            "or hiring. E.g. «how many design projects are paused for Ilya and for what amount?»"
        ),
    },
    "thinking": {"ru": "🤔 Смотрю данные…", "en": "🤔 Looking at the data…"},
    "ask_fail": {
        "ru": "😕 Не получилось ответить на вопрос. Разделы с кнопками работают — попробуйте их или спросите позже.",
        "en": "😕 Couldn't answer the question. The button sections still work — try them or ask later.",
    },
    "ask_more": {"ru": "Можно задать ещё вопрос.", "en": "You can ask another question."},
    "no_ai": {"ru": "ИИ не подключён (нет ключа Claude).", "en": "AI isn't connected (no Claude key)."},
}


def _tx(key: str, lang: str, **kw) -> str:
    return TXT[key]["en" if lang == "en" else "ru"].format(**kw)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back(to: str = "menu") -> list[InlineKeyboardButton]:
    return [_btn("◀ Назад / Back", f"{CB}:{to}")]


def _menu_kb() -> InlineKeyboardMarkup:
    return _kb([
        [_btn("📁 Проекты / Projects", f"{CB}:pr")],
        [_btn("📊 Планы / Plans", f"{CB}:pl")],
        [_btn("👥 HR", f"{CB}:hr")],
        [_btn("💬 Спросить / Ask", f"{CB}:ask")],
        [_btn("🔄 Обновить данные / Refresh", f"{CB}:refresh")],
    ])


def _cut(text: str) -> str:
    """Telegram — до 4096 символов: режем по строкам."""
    if len(text) <= MAX_LEN:
        return text
    out = ""
    for line in text.split("\n"):
        if len(out) + len(line) + 2 > MAX_LEN:
            return out + "\n…"
        out += line + "\n"
    return out


class AskState(StatesGroup):
    waiting = State()


async def _load(key: str, config: Config, sheets, cache: SheetCache, bot, force: bool = False):
    """(данные листов, время, свежие?) или (None, текст ошибки для пользователя)."""
    sheet_id = config.mgmt_sheet_ids.get(key)
    title = TABLE_TITLES[key]
    if sheets is None or not sheet_id:
        return None, "not_set"
    try:
        return await asyncio.to_thread(cache.get, sheets, key, sheet_id, force), None
    except Exception as err:  # noqa: BLE001
        logging.exception("Управление: не удалось прочитать %s", key)
        await alert_admin(
            bot, config,
            f"⚠️ «Управление»: не удалось прочитать таблицу «{title}».\n"
            f"Причина: {html.escape(sheets.explain_error(err, role='Читатель'))}",
        )
        return None, "fail"


async def _show(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(_cut(text), reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest as err:
        if "not modified" not in str(err):
            await callback.message.answer(_cut(text), reply_markup=markup)


# --- вход ---------------------------------------------------------------------

@router.message(Command("myid"))
async def my_id(message: Message) -> None:
    """Показывает Telegram ID — чтобы собрать ID руководителей для MGMT_IDS."""
    await message.answer(f"Ваш Telegram ID / Your Telegram ID: <code>{message.from_user.id}</code>")


@router.message(F.text == kb.BTN_MGMT)
async def open_menu(message: Message, state: FSMContext, config: Config, users: UserRegistry) -> None:
    if not config.is_mgmt(message.from_user.id):
        return
    await state.clear()
    lang = users.get_lang(message.from_user.id)
    await message.answer(_tx("menu", lang), reply_markup=_menu_kb())


@router.callback_query(F.data.startswith(f"{CB}:"))
async def on_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: Config,
    users: UserRegistry,
    sheets: SheetsClient | None,
    mgmt_cache: SheetCache,
) -> None:
    if not config.is_mgmt(callback.from_user.id):
        await callback.answer()
        return
    lang = users.get_lang(callback.from_user.id)
    parts = callback.data.split(":")[1:]
    section = parts[0]

    if section == "refresh":
        mgmt_cache.clear()
        await callback.answer(_tx("refreshed", lang))
        return
    await callback.answer()
    if section == "menu":
        await state.clear()
        await _show(callback, _tx("menu", lang), _menu_kb())
        return
    if section == "ask":
        await state.set_state(AskState.waiting)
        await _show(callback, _tx("ask", lang), _kb([_back()]))
        return

    key = {"pr": PROJECTS, "pl": PLAN, "hr": HIRING}.get(section)
    if key is None:
        return
    loaded, err = await _load(key, config, sheets, mgmt_cache, callback.bot)
    if loaded is None:
        await _show(callback, _tx(err, lang, t=TABLE_TITLES[key]), _kb([_back()]))
        return
    data, at, fresh = loaded
    foot = "\n\n" + fm.footer(at, fresh, lang)
    today = now_dubai().date()

    if section == "pr":
        text, markup = _projects_view(parse_projects(data), parts[1:], today, lang)
    elif section == "pl":
        text, markup = _plan_view(parse_plans(data, today), parts[1:], today, lang)
    else:
        text, markup = _hr_view(parse_hiring(data), parts[1:], today, lang)
    await _show(callback, _cut(text) + foot, markup)


# --- экраны ---------------------------------------------------------------------

def _projects_view(pd, args: list[str], today, lang: str):
    sub = args[0] if args else ""
    if sub == "":
        return _tx("projects", lang), _kb([
            [_btn("📋 Сводка / Summary", f"{CB}:pr:sum")],
            [_btn("🏢 По отделам / By department", f"{CB}:pr:dept")],
            [_btn("👤 Загрузка по людям / Workload", f"{CB}:pr:load")],
            [_btn("✍️ Новые подписания / New signings", f"{CB}:pr:sign")],
            _back(),
        ])
    if sub == "sum":
        return fm.projects_summary(pd, lang), _kb([_back("pr")])
    if sub in ("dept", "load"):
        target = "d" if sub == "dept" else "l"
        return _tx("choose_dept", lang), _kb(
            [[_btn(fm.dept_name(d, lang), f"{CB}:pr:{target}:{d}")] for d in DEPTS] + [_back("pr")]
        )
    if sub == "d" and len(args) > 1 and args[1] in DEPTS:
        return fm.projects_dept(pd, args[1], lang), _kb([_back("pr:dept")])
    if sub == "l" and len(args) > 1 and args[1] in DEPTS:
        d = args[1]
        names = people(pd, d)
        rows = [[_btn(f"📂 {n}", f"{CB}:pr:p:{d}:{i}")] for i, n in enumerate(names[:12])]
        return fm.workload_text(pd, d, lang), _kb(rows + [_back("pr:load")])
    if sub == "p" and len(args) > 2 and args[1] in DEPTS:
        d = args[1]
        names = people(pd, d)
        i = int(args[2]) if args[2].isdigit() else -1
        if 0 <= i < len(names):
            return fm.person_list(pd, d, names[i], lang), _kb([_back(f"pr:l:{d}")])
    if sub == "sign":
        y, m = today.year, today.month
        if len(args) > 1 and "-" in args[1]:
            y, m = (int(x) for x in args[1].split("-"))
        prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
        next_y, next_m = (y, m + 1) if m < 12 else (y + 1, 1)
        nav = [_btn("◀", f"{CB}:pr:sign:{prev_y}-{prev_m}")]
        if (next_y, next_m) <= (today.year, today.month):
            nav.append(_btn("▶", f"{CB}:pr:sign:{next_y}-{next_m}"))
        return fm.signings_text(pd, y, m, lang), _kb([nav, _back("pr")])
    return _tx("projects", lang), _kb([_back("pr")])


def _plan_view(plans: dict, args: list[str], today, lang: str):
    if not plans:
        return "📊 Листы «ПЛАН …» не найдены.", _kb([_back()])
    months = sorted(plans, key=lambda m: (plans[m].year, m))
    m = int(args[0]) if args and args[0].isdigit() and int(args[0]) in plans else (
        today.month if today.month in plans else months[-1]
    )
    ps = plans[m]
    role = None
    if len(args) > 1 and args[1].isdigit() and int(args[1]) < len(ps.roles):
        role = ps.roles[int(args[1])]
    i = months.index(m)
    nav = []
    if i > 0:
        nav.append(_btn(f"◀ {fm.month_name(months[i - 1], lang)}", f"{CB}:pl:{months[i - 1]}"))
    if i < len(months) - 1:
        nav.append(_btn(f"{fm.month_name(months[i + 1], lang)} ▶", f"{CB}:pl:{months[i + 1]}"))
    rows = []
    if nav:
        rows.append(nav)
    role_btns = [_btn(("• " if r == role else "") + r, f"{CB}:pl:{m}:{j}") for j, r in enumerate(ps.roles)]
    rows += [role_btns[k : k + 2] for k in range(0, len(role_btns), 2)]
    if role:
        rows.append([_btn("📊 Все отделы / All", f"{CB}:pl:{m}")])
    rows.append(_back())
    return fm.plan_text(ps, role, today, lang), _kb(rows)


def _hr_view(hiring: dict, args: list[str], today, lang: str):
    with_data = sorted(m for m, b in hiring.items() if b)
    if not with_data:
        return "👥 В таблице найма пока нет данных.", _kb([_back()])
    m = int(args[0]) if args and args[0].isdigit() and int(args[0]) in hiring else (
        today.month if hiring.get(today.month) else with_data[-1]
    )
    blocks = hiring.get(m, [])
    rs = roles(blocks)
    nav = []
    if with_data and m in with_data:
        i = with_data.index(m)
        if i > 0:
            nav.append(_btn(f"◀ {fm.month_name(with_data[i - 1], lang)}", f"{CB}:hr:{with_data[i - 1]}"))
        if i < len(with_data) - 1:
            nav.append(_btn(f"{fm.month_name(with_data[i + 1], lang)} ▶", f"{CB}:hr:{with_data[i + 1]}"))
    if len(args) > 1 and args[1].isdigit() and int(args[1]) < len(rs):
        text = fm.hr_role_text(blocks, rs[int(args[1])], m, lang)
        return text, _kb([_back(f"hr:{m}")])
    rows = [nav] if nav else []
    btns = [_btn(r, f"{CB}:hr:{m}:{j}") for j, r in enumerate(rs[:30])]
    rows += [btns[k : k + 2] for k in range(0, len(btns), 2)]
    rows.append(_back())
    return fm.hr_overview(blocks, m, lang), _kb(rows)


# --- 💬 Спросить ----------------------------------------------------------------

@router.message(AskState.waiting, F.text | F.voice)
async def ask_question(
    message: Message,
    state: FSMContext,
    config: Config,
    users: UserRegistry,
    sheets: SheetsClient | None,
    mgmt_cache: SheetCache,
    knowledge: KnowledgeService,
    transcriber: Transcriber,
) -> None:
    if not config.is_mgmt(message.from_user.id):
        await state.clear()
        return
    if message.text and message.text in _MAIN_BUTTONS:
        await state.clear()
        raise SkipHandler  # нажата кнопка главного меню — пусть её обработает свой раздел
    lang = users.get_lang(message.from_user.id)
    if knowledge.answerer is None:
        await message.answer(_tx("no_ai", lang))
        return
    await message.answer(_tx("thinking", lang))
    await message.bot.send_chat_action(message.chat.id, "typing")

    question = message.text or ""
    if message.voice:
        try:
            question, _ = await voice_to_text(message.bot, message.voice, transcriber)
        except Exception:  # noqa: BLE001
            logging.exception("Управление: не удалось распознать голосовой вопрос")
            question = ""
        if not question:
            await message.answer(_tx("ask_fail", lang))
            return

    today = now_dubai().date()
    loaded = {}
    times = []
    for key in (PROJECTS, PLAN, HIRING):
        res, _ = await _load(key, config, sheets, mgmt_cache, message.bot)
        if res:
            loaded[key] = res[0]
            times.append(res[1])
    pd = parse_projects(loaded[PROJECTS]) if PROJECTS in loaded else None
    plans = parse_plans(loaded[PLAN], today) if PLAN in loaded else {}
    hiring = parse_hiring(loaded[HIRING]) if HIRING in loaded else {}
    tools = _tools(pd, plans, hiring, today)
    at = min(times).strftime("%H:%M") if times else "—"
    context = (
        f"Сегодня {today:%d.%m.%Y} (Дубай). Данные таблиц на {at}. "
        f"Доступные таблицы: {', '.join(TABLE_TITLES[k] for k in loaded) or 'нет'}."
    )
    try:
        answer = await knowledge.answerer.answer_management_question(
            question, tools, context, model=config.mgmt_model or None
        )
    except Exception as err:  # noqa: BLE001
        logging.exception("Управление: Claude не ответил")
        await alert_admin(
            message.bot, config,
            f"⚠️ «Управление → Спросить»: Claude не ответил.\nПричина: {html.escape(describe_error(err))}",
        )
        await message.answer(_tx("ask_fail", lang), reply_markup=_kb([_back()]))
        return
    if not answer:
        await message.answer(_tx("ask_fail", lang), reply_markup=_kb([_back()]))
        return
    prefix = f"🎙 <i>{html.escape(question)}</i>\n\n" if message.voice else ""
    await message.answer(
        _cut(prefix + render_markdown(answer)) + f"\n\n<i>{_tx('ask_more', lang)}</i>",
        reply_markup=_kb([_back()]),
    )


_MAIN_BUTTONS = {
    kb.BTN_KNOWLEDGE, kb.BTN_SEND_DATA, kb.BTN_AGREEMENTS, kb.BTN_BLACKBOX, kb.BTN_MGMT,
    kb.BTN_BROADCAST, kb.BTN_REFRESH, kb.BTN_BALANCE, kb.BTN_HELP, kb.BTN_LANG, kb.BTN_CANCEL,
}


def _tools(pd, plans: dict, hiring: dict, today) -> dict:
    import datetime as dt

    def _date(s):
        try:
            return dt.date.fromisoformat(s) if s else None
        except ValueError:
            return None

    def get_projects(department=None, status=None, person=None, signed_from=None, signed_to=None):
        if pd is None:
            return {"error": "мастер-таблица недоступна"}
        return query_projects(pd, department, status, person, _date(signed_from), _date(signed_to))

    def get_workload(department=None):
        if pd is None:
            return {"error": "мастер-таблица недоступна"}
        depts = [department] if department in DEPTS else list(DEPTS)
        return {d: pd.workload.get(d, []) for d in depts}

    def get_plan(month, department=None):
        ps = plans.get(int(month))
        if ps is None:
            return {"error": f"нет листа плана за месяц {month}", "available_months": sorted(plans)}
        return plan_query(ps, department, today)

    def get_hiring(role=None, month=None, week=None):
        m = int(month) if month else today.month
        blocks = hiring.get(m)
        if not blocks:
            return {"error": f"нет данных найма за месяц {m}", "available_months": sorted(k for k, v in hiring.items() if v)}
        return hiring_query(blocks, role, week)

    return {
        "get_projects": get_projects,
        "get_workload": get_workload,
        "get_plan": get_plan,
        "get_hiring": get_hiring,
    }


# --- админ ----------------------------------------------------------------------

@router.message(Command("mgmt_ping"))
async def mgmt_ping(message: Message, config: Config, sheets: SheetsClient | None) -> None:
    """Админ: видит ли бот все три таблицы и все нужные листы."""
    if not config.is_admin(message.from_user.id):
        return
    if sheets is None:
        await message.answer("❌ Google Sheets не подключены (нет google_credentials.json).")
        return
    await message.answer("🔎 Проверяю доступ к таблицам…")
    try:
        lines = await asyncio.to_thread(ping, sheets, config.mgmt_sheet_ids, now_dubai().date())
    except Exception:  # noqa: BLE001
        logging.exception("Управление: ошибка /mgmt_ping")
        await message.answer("❌ Проверка упала с ошибкой — подробности в логах.")
        return
    lines = ["🔎 <b>Доступ к таблицам «Управления»</b>", ""] + lines
    lines.append(f"Почта бота: <code>{sheets.email}</code>")
    await _send_lines(message, lines)


@router.message(Command("mgmt_check"))
async def mgmt_check(
    message: Message, config: Config, sheets: SheetsClient | None, mgmt_cache: SheetCache
) -> None:
    """Админ: что не заполнено или заполнено криво в таблицах (влияет на цифры)."""
    if not config.is_admin(message.from_user.id):
        return
    today = now_dubai().date()
    lines = ["🧹 <b>Контроль заполнения таблиц</b>", ""]
    for key in (PROJECTS, PLAN, HIRING):
        res, err = await _load(key, config, sheets, mgmt_cache, message.bot, force=True)
        title = TABLE_TITLES[key]
        if res is None:
            lines += [f"❌ <b>{title}</b>: {'нет ID в .env' if err == 'not_set' else 'не удалось прочитать'}", ""]
            continue
        data = res[0]
        if key == PROJECTS:
            issues = parse_projects(data).issues
        elif key == PLAN:
            issues = [i for ps in parse_plans(data, today).values() for i in ps.issues]
        else:
            issues = [
                f"лист «{MONTHS_EN[m - 1]}»: блоков ролей не найдено (пустой?)"
                for m, b in parse_hiring(data).items() if not b
            ]
        lines.append(f"<b>{title}</b>: " + (f"замечаний {len(issues)}" if issues else "✅ замечаний нет"))
        for i in issues[:40]:
            lines.append(f"• {html.escape(i)}")
        if len(issues) > 40:
            lines.append(f"… и ещё {len(issues) - 40}")
        lines.append("")
    await _send_lines(message, lines)


async def _send_lines(message: Message, lines: list[str]) -> None:
    """Режем длинный отчёт по строкам, чтобы не разорвать HTML-теги."""
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            await message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await message.answer(chunk)


@router.message(Command("mgmt_plan_raw"))
async def mgmt_plan_raw(
    message: Message, config: Config, sheets: SheetsClient | None, mgmt_cache: SheetCache
) -> None:
    """Админ: какие ячейки листа плана бот читает для показателей отдела.

    /mgmt_plan_raw HR  ·  /mgmt_plan_raw 10 Маркетинг (10 — номер месяца)
    """
    if not config.is_admin(message.from_user.id):
        return
    from gspread.utils import rowcol_to_a1

    args = (message.text or "").split(maxsplit=1)[1:] or [""]
    words = args[0].split()
    today = now_dubai().date()
    month = int(words[0]) if words and words[0].isdigit() else today.month
    role = " ".join(w for w in words if not w.isdigit())
    res, err = await _load(PLAN, config, sheets, mgmt_cache, message.bot, force=True)
    if res is None:
        await message.answer("❌ Таблица план-факта недоступна.")
        return
    data = res[0]
    plans = parse_plans(data, today)
    ps = plans.get(month)
    if ps is None:
        await message.answer(f"Нет листа плана за месяц {month}. Есть: {sorted(plans)}")
        return
    raw = data[ps.title]
    lines = [f"🔬 <b>{html.escape(ps.title)}</b>", "Недели (колонка факта / колонка %):"]
    for w in ps.weeks:
        pct = rowcol_to_a1(1, w.pct_col + 1)[:-1] if w.pct_col is not None else "—"
        lines.append(f"• {html.escape(w.label)}: {rowcol_to_a1(1, w.col + 1)[:-1]} / {pct}")
    lines.append("")
    for ind in ps.indicators:
        if role and role.casefold() not in ind.role.casefold():
            continue
        row = raw[ind.row - 1] if ind.row - 1 < len(raw) else []
        cells = []
        for w in ps.weeks:
            v = row[w.col] if w.col < len(row) else ""
            p = row[w.pct_col] if w.pct_col is not None and w.pct_col < len(row) else ""
            cells.append(f"{rowcol_to_a1(ind.row, w.col + 1)}={v!r} ({p!r})")
        lines.append(
            f"<b>{html.escape(ind.role)} · {html.escape(ind.name)}</b> (строка {ind.row}), "
            f"план {ind.plan!r}\n   " + html.escape("; ".join(cells), quote=False)
        )
    await _send_lines(message, lines)
