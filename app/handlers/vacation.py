"""«🌴 Мой отпуск» — сотрудник видит свои отпускные дни из таблицы HR.

Бот узнаёт человека (колонка «Telegram» в таблице → привязка /vac_link → имя в
Telegram совпадает с ФИО), читает таблицу отпусков (кэш 5 минут) и показывает:
положено / перенос / использовано / осталось, отпуска по датам (прошедшие и
запланированные), больничные и прочее, правила из регламента. Каждый видит
только себя. Денег не показываем — только дни.

Админ: /vac_link <ID или @ник> <Фамилия Имя> — привязать человека к строке
таблицы; /vac_list — кто из таблицы ещё не узнан ботом.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app import keyboards as kb
from app import vacation as vac
from app.expenses import now_dubai
from app.management_data import SheetCache
from app.notify import alert_admin
from app.sheets import SheetsClient
from app.users import UserRegistry
from config import Config

router = Router()

CACHE_KEY = "vacation"
HR_CONTACT = "@miamishel"
NOTICE_DAYS = 60  # заявку подавать минимум за 60 календарных дней (регламент)

# Подписи разбивки с листа «Totals» → по-русски. Holiday не повторяем (это «использовано»).
BREAKDOWN_RU = {
    "half day (morning)": "полдня (утро)", "half day (afternoon)": "полдня (после обеда)",
    "quarter day": "четверть дня", "custom deductible": "прочее за счёт отпуска",
    "sickness": "больничные", "maternity/paternity": "декрет",
    "time off in lieu": "отгулы за переработку", "work from home": "удалёнка",
    "compassionate": "по семейным обстоятельствам",
}

# Эти виды отсутствия не уменьшают отпуск — показываем отдельно, для справки.
NOT_DEDUCTED = {"sickness", "maternity/paternity", "time off in lieu", "work from home", "compassionate"}

e = html.escape


def _rules(lang: str, today: dt.date) -> str:
    earliest = today + dt.timedelta(days=NOTICE_DAYS)
    if lang == "en":
        return (
            "<b>How to take leave</b>\n"
            f"• Request at least {NOTICE_DAYS} days in advance — so you can now plan dates from <b>{earliest:%d.%m.%Y}</b>\n"
            f"• First message HR {HR_CONTACT}: HR checks the dates and agrees them with your manager and the CEO\n"
            "• Leave must not overlap with colleagues in the same or a related role\n"
            "• Paid leave is available after 6 months of work with the company\n"
            "• A week before your leave, notify colleagues — with «📣 Report absence»"
        )
    return (
        "<b>Как взять отпуск</b>\n"
        f"• Заявку подавать минимум за {NOTICE_DAYS} дней — то есть сейчас можно планировать даты с <b>{earliest:%d.%m.%Y}</b>\n"
        f"• Сначала напишите HR {HR_CONTACT}: HR проверит даты и согласует с руководителем и CEO\n"
        "• Отпуск не должен пересекаться с коллегами той же или смежной должности\n"
        "• Право на оплачиваемый отпуск — после 6 месяцев работы в компании\n"
        "• За неделю до отпуска предупредите коллег — кнопкой «📣 Сообщить об отсутствии»"
    )


def info_text(emp: vac.Employee, first_name: str, year: int | None, today: dt.date,
              lang: str, at: dt.datetime, fresh: bool) -> str:
    n = vac.fmt_num
    en = lang == "en"
    yesterday = today - dt.timedelta(days=1)
    past = vac.ranges(emp, vac.VACATION_CODES, end=yesterday)
    future = vac.ranges(emp, vac.VACATION_CODES, start=today)
    hello = f"🌴 <b>{e(first_name)}, " + ("hello! Your leave" if en else "здравствуйте! Ваш отпуск")
    lines = [hello + (f" for {year}" if en else f" на {year} год") + ":</b>" if year else hello + ":</b>", ""]
    days = "days" if en else "дн."
    if emp.carry:
        sign = "+" if emp.carry > 0 else "−"
        note = "carried over from last year" if en else "перенос с прошлого года"
        lines.append(
            f"{'Entitled' if en else 'Положено'}: {n(emp.base)} {sign} {n(abs(emp.carry))} ({note})"
            f" = <b>{n(emp.total)}</b> {days}"
        )
    else:
        lines.append(f"{'Entitled' if en else 'Положено'}: <b>{n(emp.total)}</b> {days}")
    lines.append(f"{'Used and booked' if en else 'Использовано и запланировано'}: {n(emp.used)} {'days' if en else 'дн.'}")
    rem = emp.remaining
    if rem is not None and rem < 0:
        lines.append(
            f"⚠️ <b>{'Overdrawn' if en else 'Перерасход'}: {n(-rem)} {'days' if en else 'дн.'}</b> — "
            + (f"please check with HR {HR_CONTACT}" if en else f"уточните у HR {HR_CONTACT}")
        )
    else:
        lines.append(f"✅ <b>{'Days left' if en else 'Осталось'}: {n(rem)} {'days' if en else 'дн.'}</b>")
    lines.append("")
    lines.append(f"🗓 {'Booked' if en else 'Запланировано'}: " + (
        ", ".join(vac.fmt_range(a, b, w, lang) for a, b, w in future) if future
        else ("nothing yet" if en else "пока ничего")
    ))
    if past:
        lines.append(f"📅 {'Already taken' if en else 'Уже были в отпуске'}: "
                     + ", ".join(vac.fmt_range(a, b, w, lang) for a, b, w in past))
    other = [
        f"{label if en else BREAKDOWN_RU.get(vac.norm(label), label)} — {n(v)}"
        for label, v in emp.breakdown.items() if vac.norm(label) in NOT_DEDUCTED
    ]
    if other:
        lines.append(f"ℹ️ {'Not deducted from leave' if en else 'Не списываются с отпуска'}: " + "; ".join(other))
    lines += ["", _rules(lang, today), "",
              f"🕒 {'data as of' if en else 'данные на'} {at:%H:%M} ({'Dubai' if en else 'Дубай'})"
              + ("" if fresh else (" · refresh failed" if en else " · обновить не удалось"))]
    return "\n".join(lines)


async def _load(config: Config, sheets, cache: SheetCache, bot, force: bool = False):
    if sheets is None or not config.vacation_sheet_id:
        return None
    try:
        return await asyncio.to_thread(cache.get, sheets, CACHE_KEY, config.vacation_sheet_id, force)
    except Exception as err:  # noqa: BLE001
        await alert_admin(
            bot, config,
            "⚠️ «Мой отпуск»: не удалось прочитать таблицу отпусков.\n"
            f"Причина: {e(sheets.explain_error(err, role='Читатель'))}",
        )
        return None


@router.message(F.text == kb.BTN_ABS_VACATION)
async def my_vacation(
    message: Message, config: Config, users: UserRegistry,
    sheets: SheetsClient | None, mgmt_cache: SheetCache,
) -> None:
    lang = users.get_lang(message.from_user.id)
    en = lang == "en"
    loaded = await _load(config, sheets, mgmt_cache, message.bot)
    if loaded is None:
        await message.answer(
            "😕 The vacation table isn't available right now — the admin has been notified."
            if en else "😕 Таблица отпусков сейчас недоступна — админ уже знает.",
            reply_markup=kb.absence_menu(),
        )
        return
    data, at, fresh = loaded
    vd = vac.parse_vacation(data)
    user = message.from_user
    emp = vac.find_employee(vd, user.id, user.username or "", user.full_name or "")
    if emp is None:
        await message.answer(
            ("I couldn't find you in the vacation table yet. The admin has been notified — "
             f"you'll be linked soon. Meanwhile, HR {HR_CONTACT} can tell you your balance.")
            if en else
            ("Пока не нашёл вас в таблице отпусков. Админ уже знает и скоро привяжет. "
             f"А пока остаток дней подскажет HR {HR_CONTACT}."),
            reply_markup=kb.absence_menu(),
        )
        who = e(user.full_name or "") + (f" (@{e(user.username)})" if user.username else "")
        await alert_admin(
            message.bot, config,
            f"🌴 «Мой отпуск»: не узнал сотрудника {who}, ID <code>{user.id}</code>.\n"
            f"Привяжите к строке таблицы командой:\n<code>/vac_link {user.id} Фамилия Имя</code>",
        )
        return
    await message.answer(
        info_text(emp, user.first_name or emp.name, vd.year, now_dubai().date(), lang, at, fresh),
        reply_markup=kb.absence_menu(),
    )


@router.message(Command("vac_link"))
async def vac_link(
    message: Message, config: Config, users: UserRegistry,
    sheets: SheetsClient | None, mgmt_cache: SheetCache,
) -> None:
    """Админ: /vac_link <ID или @ник> <Фамилия Имя> — привязать человека к строке таблицы."""
    if not config.is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: <code>/vac_link 123456789 Фамилия Имя</code> или <code>/vac_link @ник Фамилия Имя</code>")
        return
    who, name = parts[1], parts[2]
    uid = int(who) if who.isdigit() else users.find_by_username(who)
    if uid is None:
        await message.answer(f"Не знаю пользователя {e(who)} — пусть он сначала нажмёт /start в боте.")
        return
    loaded = await _load(config, sheets, mgmt_cache, message.bot, force=True)
    if loaded is None:
        await message.answer("❌ Таблица отпусков недоступна (проверьте VACATION_SHEET_ID и доступ бота).")
        return
    emp = vac.match_name(vac.parse_vacation(loaded[0]), name)
    if emp is None:
        await message.answer(f"Не нашёл в таблице «{e(name)}» (или нашлось несколько). Напишите ФИО точнее.")
        return
    vac.save_link(uid, emp.name)
    await message.answer(f"✅ Привязал: ID <code>{uid}</code> → «{e(emp.name)}».")


@router.message(Command("vac_list"))
async def vac_list(
    message: Message, config: Config, users: UserRegistry,
    sheets: SheetsClient | None, mgmt_cache: SheetCache,
) -> None:
    """Админ: кого из таблицы отпусков бот узнаёт, а кого нужно привязать."""
    if not config.is_admin(message.from_user.id):
        return
    loaded = await _load(config, sheets, mgmt_cache, message.bot, force=True)
    if loaded is None:
        await message.answer("❌ Таблица отпусков недоступна (проверьте VACATION_SHEET_ID и доступ бота).")
        return
    vd = vac.parse_vacation(loaded[0])
    found: dict[str, str] = {}
    for uid, name, username in users.entries():
        emp = vac.find_employee(vd, uid, username, name)
        if emp:
            found[emp.name] = f"{name}" + (f" (@{username})" if username else "")
    lines = [f"🌴 <b>Таблица отпусков {vd.year or ''}</b>: {len(vd.employees)} сотрудников", ""]
    for emp in vd.employees.values():
        mark = f"✅ {e(found[emp.name])}" if emp.name in found else "❌ не узнан"
        lines.append(f"• {e(emp.name)} — {mark}")
    lines += ["", "Привязать: <code>/vac_link ID-или-@ник Фамилия Имя</code>"]
    if vd.issues:
        lines += ["", "Замечания по таблице:"] + [f"• {e(i)}" for i in vd.issues[:15]]
    await message.answer("\n".join(lines))
