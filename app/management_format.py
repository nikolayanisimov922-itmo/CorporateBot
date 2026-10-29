"""Тексты ответов раздела «📈 Управление» (Telegram, HTML)."""
from __future__ import annotations

import datetime as dt
import html

from app.expenses import MONTHS_EN, MONTHS_RU
from app.management_data import fmt_num, norm
from app.mgmt_hiring import STAGES, funnel, last_week, roles
from app.mgmt_plan import PlanSheet, evaluate, workdays_share
from app.mgmt_projects import (
    ACTIVE,
    DEPT_EN,
    DEPT_RU,
    DEPTS,
    NOTYPE,
    PAUSED,
    DEPT_SHEET,
    ProjectsData,
    dept_summary,
    person_projects,
    signed_in_month,
    strip_number,
    summary,
)

e = html.escape

L = {
    "asof": {"ru": "данные на {t} (Дубай)", "en": "data as of {t} (Dubai)"},
    "stale": {"ru": " · обновить не удалось", "en": " · refresh failed"},
    "total": {"ru": "Всего", "en": "Total"},
    "active": {"ru": "В работе", "en": "In progress"},
    "paused": {"ru": "На паузе", "en": "On pause"},
    "done": {"ru": "Завершено", "en": "Completed"},
    "refused": {"ru": "Отказы", "en": "Refused"},
    "new": {"ru": "Новые", "en": "New"},
    "unknown": {"ru": "Без статуса", "en": "No status"},
    "by_dept": {"ru": "По отделам (в работе / пауза)", "en": "By department (in progress / paused)"},
    "notype": {"ru": "Без типа", "en": "No type"},
    "projects_n": {"ru": "проектов", "en": "projects"},
    "money": {"ru": "Деньги по проектам в работе (In Progress)", "en": "Money for projects in progress"},
    "src_dept": {"ru": "по листу «{s}»", "en": "from the «{s}» sheet"},
    "contract": {"ru": "контракты", "en": "contracts"},
    "paid": {"ru": "оплачено", "en": "paid"},
    "remaining": {"ru": "остаток", "en": "remaining"},
    "signed": {"ru": "Новые подписания", "en": "New signings"},
    "none": {"ru": "нет", "en": "none"},
    "load": {"ru": "Загрузка", "en": "Workload"},
    "load_none": {"ru": "Лист «Загрузка» пустой или не найден.", "en": "The workload sheet is empty or missing."},
    "rem_pay": {"ru": "остаток оплат", "en": "payments due"},
    "pause_n": {"ru": "на паузе", "en": "paused"},
    "plan": {"ru": "План", "en": "Plan"},
    "plan_none": {"ru": "План на {m} ещё не внесён.", "en": "The plan for {m} hasn't been entered yet."},
    "plan_upto": {
        "ru": "Факт накопительно за месяц · заполнено недель: {n} из {total} (последняя {w})",
        "en": "Month-to-date actuals · weeks filled: {n} of {total} (last {w})",
    },
    "plan_nofact": {"ru": "фактов ещё нет", "en": "no actuals yet"},
    "pace": {"ru": "Ожидаемый темп на сегодня: ~{p}%", "en": "Expected pace today: ~{p}%"},
    "no_plan": {"ru": "план не задан", "en": "no plan set"},
    "within": {"ru": "в рамках", "en": "within plan"},
    "over": {"ru": "превышен", "en": "over plan"},
    "hr_none": {"ru": "В листе найма за {m} нет данных.", "en": "No hiring data for {m}."},
    "hr_month": {"ru": "За {m}", "en": "For {m}"},
    "hr_sources": {"ru": "Источники откликов", "en": "Response sources"},
    "hr_noweek": {"ru": "за последнюю неделю откликов нет", "en": "no responses in the last week"},
}


def plural(n: float | None, lang: str) -> str:
    """«1 проект», «2 проекта», «5 проектов» / «1 project», «2 projects»."""
    if n is None:
        return "—"
    k = int(n)
    if lang == "en":
        return f"{k} project" + ("" if k == 1 else "s")
    if k % 10 == 1 and k % 100 != 11:
        w = "проект"
    elif 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14:
        w = "проекта"
    else:
        w = "проектов"
    return f"{k} {w}"


def tr(key: str, lang: str, **kw) -> str:
    return L[key]["en" if lang == "en" else "ru"].format(**kw)


def footer(at: dt.datetime, fresh: bool, lang: str) -> str:
    s = "🕒 " + tr("asof", lang, t=at.strftime("%H:%M"))
    return s + (tr("stale", lang) if not fresh else "")


def dept_name(d: str, lang: str) -> str:
    return (DEPT_EN if lang == "en" else DEPT_RU)[d]


def month_name(m: int, lang: str) -> str:
    return (MONTHS_EN if lang == "en" else MONTHS_RU)[m - 1]


# --- Проекты ----------------------------------------------------------------------

def projects_summary(pd: ProjectsData, lang: str) -> str:
    s = summary(pd)
    st = s["by_status"]
    lines = [
        f"📁 <b>{'Projects — summary' if lang == 'en' else 'Проекты — сводка'}</b>",
        "",
        f"{tr('total', lang)}: <b>{s['total']}</b>",
        f"🟢 {tr('active', lang)}: <b>{st[ACTIVE]}</b>   ⏸ {tr('paused', lang)}: <b>{st[PAUSED]}</b>",
        f"✅ {tr('done', lang)}: {st['completed']}   ❌ {tr('refused', lang)}: {st['refused']}",
    ]
    if st["new"]:
        lines.append(f"🆕 {tr('new', lang)}: {st['new']}")
    if st["unknown"]:
        lines.append(f"❔ {tr('unknown', lang)}: {st['unknown']}")
    lines += ["", f"<b>{tr('by_dept', lang)}:</b>"]
    for d in DEPTS:
        x = s["by_dept"][d]
        lines.append(f"• {dept_name(d, lang)}: {x['active']} / {x['paused']}")
    if s["by_dept"][NOTYPE]["total"]:
        lines.append(f"⚠️ {tr('notype', lang)}: {s['by_dept'][NOTYPE]['total']}")
    return "\n".join(lines)


def projects_dept(pd: ProjectsData, d: str, lang: str) -> str:
    x = dept_summary(pd, d)
    lines = [
        f"📁 <b>{dept_name(d, lang)}</b>",
        f"<i>{tr('src_dept', lang, s=DEPT_SHEET[d])}</i>",
        "",
        f"{tr('total', lang)}: {x['total']}",
        f"🟢 {tr('active', lang)}: {x['active']} · {fmt_num(x['area_active'])} м²",
        f"⏸ {tr('paused', lang)}: {x['paused']}",
        "",
        f"<b>{tr('money', lang)}:</b>",
        f"• {tr('contract', lang)}: {fmt_num(x['contract'], True)}",
        f"• {tr('paid', lang)}: {fmt_num(x['paid'], True)}",
        f"• {tr('remaining', lang)}: {fmt_num(x['remaining'], True)}",
    ]
    return "\n".join(lines)


def workload_text(pd: ProjectsData, d: str, lang: str) -> str:
    rows = pd.workload.get(d) or []
    head = f"👤 <b>{tr('load', lang)} — {dept_name(d, lang)}</b>"
    if not rows:
        return head + "\n\n" + tr("load_none", lang)
    lines = [head, ""]
    for r in rows:
        parts = [plural(r.get("projects"), lang)]
        if r.get("area") is not None:
            parts.append(f"{fmt_num(r['area'])} м²")
        if r.get("paused") is not None:
            parts.append(f"{tr('pause_n', lang)} {fmt_num(r['paused'])}")
        if r.get("remaining") is not None:
            parts.append(f"{tr('rem_pay', lang)} {fmt_num(r['remaining'], True)}")
        name = f"<b>{e(r['name'])}</b>" if r["total"] else e(r["name"])
        lines.append(f"{name} — " + " · ".join(parts))
    return "\n".join(lines)


def person_list(pd: ProjectsData, d: str, name: str, lang: str, limit: int = 40) -> str:
    ps = person_projects(pd, d, name)
    active = sum(1 for p in ps if p.status == ACTIVE)
    lines = [
        f"👤 <b>{e(name)}</b> — {dept_name(d, lang)}",
        f"🟢 {tr('active', lang)}: {active}   ⏸ {tr('paused', lang)}: {len(ps) - active}",
        "",
    ]
    for p in ps[:limit]:
        icon = "🟢" if p.status == ACTIVE else "⏸"
        area = f" · {fmt_num(p.area)} м²" if p.area is not None else ""
        rem = f" · {tr('remaining', lang)} {fmt_num(p.remaining, True)}" if p.remaining else ""
        lines.append(f"{icon} {e(p.number)} {e(strip_number(p.name, p.number))}{area}{rem}")
    if len(ps) > limit:
        lines.append(f"… +{len(ps) - limit}")
    return "\n".join(lines)


def signings_text(pd: ProjectsData, year: int, month: int, lang: str) -> str:
    ps = signed_in_month(pd, year, month)
    lines = [f"✍️ <b>{tr('signed', lang)} — {month_name(month, lang)} {year}: {len(ps)}</b>", ""]
    if not ps:
        lines.append(tr("none", lang))
    by_dept = {}
    for p in ps:
        by_dept.setdefault(p.dept, []).append(p)
    for d, items in by_dept.items():
        total = sum(p.revenue for p in items if p.revenue is not None)
        lines.append(f"<b>{dept_name(d, lang)}</b> — {len(items)}" + (f" · {fmt_num(total, True)}" if total else ""))
        for p in items[:30]:
            rev = f" · {fmt_num(p.revenue, True)}" if p.revenue is not None else ""
            lines.append(f"• {p.signed:%d.%m} {e(p.number)} {e(strip_number(p.name, p.number))}{rev}")
        lines.append("")
    return "\n".join(lines).strip()


# --- Планы ------------------------------------------------------------------------

def plan_text(ps: PlanSheet, role: str | None, today: dt.date, lang: str) -> str:
    m = f"{month_name(ps.month, lang)} {ps.year}"
    title = f"📊 <b>{tr('plan', lang)} — {m}" + (f" · {e(role)}" if role else "") + "</b>"
    if not ps.has_plan:
        return title + "\n\n" + tr("plan_none", lang, m=month_name(ps.month, lang).lower())
    cw = ps.current_week
    upto = (
        tr("plan_upto", lang, n=cw + 1, total=len(ps.weeks), w=e(ps.weeks[cw].label))
        if cw is not None else tr("plan_nofact", lang)
    )
    pace = workdays_share(ps.year, ps.month, today)
    lines = [title, f"<i>{upto}</i>", ""]
    current_role = None
    for ind in ps.indicators:
        if role and ind.role != role:
            continue
        if not role and ind.role != current_role:
            current_role = ind.role
            lines.append(f"\n<b>{e(ind.role)}</b>")
        r = evaluate(ind, cw, pace)
        fact = fmt_num(r.fact, ind.money)
        plan = fmt_num(ind.plan, ind.money)
        if r.status == "⚪" and ind.plan in (None, 0):
            lines.append(f"⚪ {e(ind.name)}: {fact} ({tr('no_plan', lang)})")
        elif ind.kind == "computed":
            word = tr("within", lang) if r.status == "✅" else (tr("over", lang) if r.status == "⚠️" else "")
            avg = "среднее " if lang != "en" else "avg "
            lines.append(f"{r.status} {e(ind.name)}: {avg}{fact} / {plan}" + (f" — {word}" if word else ""))
        elif ind.kind == "inverse":
            word = tr("within", lang) if r.status == "✅" else (tr("over", lang) if r.status == "⚠️" else "")
            lines.append(f"{r.status} {e(ind.name)}: {fact} / {plan}" + (f" — {word}" if word else ""))
        else:
            lines.append(f"{r.status} {e(ind.name)}: {fact} / {plan} ({round(r.pct * 100)}%)")
    lines += ["", tr("pace", lang, p=round(pace * 100))]
    return "\n".join(lines).replace("\n\n\n", "\n\n")


# --- HR ---------------------------------------------------------------------------

def _funnel_line(f: dict, lang: str) -> str:
    st = f["stages"]
    base = st.get("responses") or 0
    parts = []
    for code, ru, _ in STAGES:
        if code not in f["present"]:
            continue
        name = ru if lang != "en" else code.capitalize()
        v = st.get(code, 0)
        if code == "responses" or not base:
            parts.append(f"{name} {fmt_num(v)}")
        else:
            parts.append(f"{name} {fmt_num(v)} ({round(v / base * 100)}%)")
    return " → ".join(parts) if parts else "—"


def hr_role_text(blocks, role: str, month: int, lang: str) -> str:
    week = last_week(blocks, role)
    lines = [f"👥 <b>HR — {e(role)}</b>"]
    if week:
        f = funnel(blocks, role, week)
        lines += [f"<i>{e(week)}</i>", _funnel_line(f, lang)]
        if f["sources"]:
            src = ", ".join(f"{e(k)} {fmt_num(v)}" for k, v in sorted(f["sources"].items(), key=lambda x: -x[1]))
            lines.append(f"{tr('hr_sources', lang)}: {src}")
    else:
        lines.append(tr("hr_noweek", lang))
    fm = funnel(blocks, role)
    lines += ["", f"<b>{tr('hr_month', lang, m=month_name(month, lang).lower())}:</b> " + _funnel_line(fm, lang)]
    return "\n".join(lines)


def hr_overview(blocks, month: int, lang: str) -> str:
    if not blocks:
        return tr("hr_none", lang, m=month_name(month, lang).lower())
    lines = [f"👥 <b>HR — {month_name(month, lang)}</b>", ""]
    for r in roles(blocks):
        f = funnel(blocks, r)
        st = f["stages"]
        lines.append(
            f"• {e(r)}: {fmt_num(st['responses'])} → {fmt_num(st['offer'])} → {fmt_num(st['joining'])}"
        )
    lines += ["", "<i>" + ("отклики → офферы → выход" if lang != "en" else "responses → offers → joined") + "</i>"]
    return "\n".join(lines)


def find_role(blocks, name: str) -> str | None:
    return next((r for r in roles(blocks) if norm(r) == norm(name)), None)
