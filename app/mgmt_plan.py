"""«📊 Планы»: разбор листов «ПЛАН <МЕСЯЦ>» и выполнение плана (чистые функции).

Структура листа: строка 1 — «Роль | Показатель | План на месяц | Неделя 01.10 - 02.10 |…»
(неделя — блок из 4 колонок: «Факт» ×2 и «% плана месяца (накоп.)» ×2), строка 2 —
подписи «Факт» / «%», данные с 3-й строки; «Роль» заполнена только в первой строке
блока → протягиваем вниз.

% выполнения считаем сами (сумма фактов / план) — колонка «% накоп.» в таблице
ломается на пустых неделях. Обратные показатели (бюджеты, стоимость лида): меньше —
лучше, показываем «в рамках / превышен». Расчётные (стоимость SQL/MQL) не суммируем —
берём значение последней заполненной недели.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from app.expenses import MONTHS_RU
from app.management_data import cell, find_header, norm, to_num

_DATES = re.compile(r"(\d{1,2})\.(\d{1,2})")


@dataclass
class Week:
    label: str
    col: int  # колонка «Факт»
    months: set = field(default_factory=set)  # месяцы из дат в заголовке


@dataclass
class Indicator:
    role: str
    name: str
    plan: float | None
    facts: list  # по неделям, None — не заполнено
    kind: str  # "sum" | "inverse" | "computed"
    money: bool = False


@dataclass
class PlanSheet:
    title: str
    month: int
    year: int
    weeks: list[Week]
    indicators: list[Indicator]
    issues: list[str]

    @property
    def roles(self) -> list[str]:
        out = []
        for i in self.indicators:
            if i.role not in out:
                out.append(i.role)
        return out

    @property
    def current_week(self) -> int | None:
        """Последняя неделя, где есть хоть один факт."""
        last = None
        for w in range(len(self.weeks)):
            if any(i.facts[w] is not None for i in self.indicators):
                last = w
        return last

    @property
    def has_plan(self) -> bool:
        return any(i.plan is not None for i in self.indicators)


def month_of_title(title: str) -> int | None:
    n = norm(title)
    if not n.startswith("план"):
        return None
    for i, m in enumerate(MONTHS_RU, start=1):
        if m.casefold() in n:
            return i
    return None


def _kind(name: str) -> tuple[str, bool]:
    n = norm(name)
    money = any(w in n for w in ("деньг", "сумма", " dh", "бюджет", "стоимость"))
    if "стоимость" in n:
        return "computed", money
    if "бюджет" in n:
        return "inverse", money
    return "sum", money


def year_for(month: int, today: dt.date) -> int:
    """Год в имени листа не указан. Считаем, что листы — в пределах года вокруг
    сегодняшнего дня: в октябре «ДЕКАБРЬ» — этот год, в январе «ДЕКАБРЬ» — прошлый."""
    delta = month - today.month
    if delta > 2:
        return today.year - 1
    if delta < -9:
        return today.year + 1
    return today.year


def parse_plan_sheet(title: str, rows: list[list], today: dt.date) -> PlanSheet | None:
    month = month_of_title(title)
    if month is None:
        return None
    year = year_for(month, today)
    issues: list[str] = []
    hit = find_header(rows, ["показатель"], max_scan=5)
    if not hit:
        issues.append(f"«{title}»: не нашёл строку заголовков (Роль / Показатель)")
        return PlanSheet(title, month, year, [], [], issues)
    h, heads = hit
    c_role = next((i for i, x in enumerate(heads) if x.startswith("роль")), 0)
    c_name = next((i for i, x in enumerate(heads) if x.startswith("показатель")), 1)
    c_plan = next((i for i, x in enumerate(heads) if x.startswith("план")), 2)

    weeks: list[Week] = []
    for i, x in enumerate(heads):
        if i <= c_plan or not x:
            continue
        dates = _DATES.findall(x)
        if x.startswith("неделя") or dates:
            raw = str(rows[h][i]).strip()
            weeks.append(Week(label=raw.replace("Неделя", "").strip() or raw, col=i,
                              months={int(m) for _, m in dates}))
    foreign = [w.label for w in weeks if w.months and month not in w.months]
    if foreign:
        issues.append(
            f"«{title}»: даты недель не из этого месяца ({', '.join(foreign[:3])}) — "
            "похоже, лист скопирован с другого месяца"
        )

    sub = rows[h + 1] if len(rows) > h + 1 else []
    has_sub = any("факт" in norm(c) for c in sub)
    start = h + 2 if has_sub else h + 1

    indicators: list[Indicator] = []
    role = ""
    for row in rows[start:]:
        r = str(cell(row, c_role) or "").strip()
        if r:
            role = r
        name = str(cell(row, c_name) or "").strip()
        if not name:
            continue
        kind, money = _kind(name)
        facts = [to_num(cell(row, w.col)) for w in weeks]
        indicators.append(Indicator(role or "—", name, to_num(cell(row, c_plan)), facts, kind, money))
    return PlanSheet(title, month, year, weeks, indicators, issues)


def parse_plans(data: dict, today: dt.date) -> dict[int, PlanSheet]:
    """{номер месяца: лист} по всем листам «ПЛАН …»."""
    out = {}
    for title, rows in data.items():
        ps = parse_plan_sheet(title, rows, today)
        if ps is not None:
            out[ps.month] = ps
    return out


def workdays_share(year: int, month: int, today: dt.date) -> float:
    """Доля прошедших рабочих дней (пн–пт) месяца — ожидаемый темп выполнения."""
    first = dt.date(year, month, 1)
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    days = [first + dt.timedelta(d) for d in range((nxt - first).days)]
    work = [d for d in days if d.weekday() < 5]
    if today >= nxt:
        return 1.0
    if today < first:
        return 0.0
    passed = [d for d in work if d <= today]
    return len(passed) / len(work) if work else 1.0


@dataclass
class Result:
    ind: Indicator
    fact: float | None
    pct: float | None
    status: str  # 🟢 🟡 🔴 ✅ ⚠️ ⚪


def evaluate(ind: Indicator, upto_week: int | None, pace: float) -> Result:
    weeks = ind.facts[: (upto_week + 1) if upto_week is not None else 0]
    filled = [x for x in weeks if x is not None]
    if ind.kind == "computed":
        fact = filled[-1] if filled else None
    else:
        fact = sum(filled) if filled else None
    if ind.plan in (None, 0):
        return Result(ind, fact, None, "⚪")
    if ind.kind in ("inverse", "computed"):
        if fact is None:
            return Result(ind, fact, None, "⚪")
        return Result(ind, fact, fact / ind.plan, "✅" if fact <= ind.plan else "⚠️")
    pct = (fact or 0) / ind.plan
    lag = pace - pct
    status = "🟢" if lag <= 0 else ("🟡" if lag <= 0.15 else "🔴")
    return Result(ind, fact, pct, status)


def plan_query(ps: PlanSheet, role: str | None, today: dt.date) -> dict:
    """Для «💬 Спросить»: показатели листа (по отделу) с фактом и % по неделям."""
    pace = workdays_share(ps.year, ps.month, today)
    cw = ps.current_week
    items = []
    for ind in ps.indicators:
        if role and norm(role) not in norm(ind.role):
            continue
        r = evaluate(ind, cw, pace)
        items.append({
            "department": ind.role, "indicator": ind.name, "plan": ind.plan,
            "fact_to_date": r.fact, "percent": round(r.pct * 100) if r.pct is not None else None,
            "status": r.status, "type": ind.kind,
            "by_week": {ps.weeks[i].label: ind.facts[i] for i in range(len(ps.weeks))},
        })
    return {
        "sheet": ps.title,
        "month": f"{MONTHS_RU[ps.month - 1]} {ps.year}",
        "facts_up_to_week": ps.weeks[cw].label if cw is not None else None,
        "expected_pace_percent": round(pace * 100),
        "plan_filled": ps.has_plan,
        "indicators": items,
    }
