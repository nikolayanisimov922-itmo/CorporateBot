"""«📊 Планы»: разбор листов «ПЛАН <МЕСЯЦ>» и выполнение плана (чистые функции).

Структура листа: строка 1 — «Роль | Показатель | План на месяц | Неделя 01.10 - 02.10 |…»
(неделя — блок из 4 колонок: «Факт» ×2 и «% плана месяца (накоп.)» ×2), строка 2 —
подписи «Факт» / «%», данные с 3-й строки; «Роль» заполнена только в первой строке
блока → протягиваем вниз.

% выполнения считаем сами (сумма фактов / план) — колонка «% накоп.» в таблице
ломается на пустых неделях. Обратные показатели (бюджеты, стоимость лида): меньше —
лучше, показываем «в рамках / превышен». Расчётные (стоимость SQL/MQL) не суммируем —
берём среднее по заполненным неделям и сравниваем с планом.
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
    pct_col: int | None = None  # колонка «% плана месяца (накоп.)» — для сверки


@dataclass
class Indicator:
    role: str
    name: str
    plan: float | None
    facts: list  # по неделям, None — не заполнено
    kind: str  # "sum" | "inverse" | "computed"
    money: bool = False
    row: int = 0  # номер строки в таблице (для /mgmt_plan_raw)
    pcts: list = field(default_factory=list)  # «% накоп.» из таблицы по неделям (доли)


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


def to_pct(v) -> float | None:
    """«14%» → 0.14; 0.14 (формат «процент») → 0.14."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    x = to_num(s)
    if x is None:
        return None
    return x / 100 if "%" in s else x


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
    # Внутри блока недели: «Факт» и «% плана (накоп.)» — по подписям второй строки.
    ends = [w.col for w in weeks[1:]] + [max((len(r) for r in rows), default=0)]
    for w, end in zip(weeks, ends):
        labels = {j: norm(sub[j]) if j < len(sub) else "" for j in range(w.col, end)}
        fact = next((j for j, x in labels.items() if x.startswith("факт")), None)
        if fact is not None:
            w.col = fact
        w.pct_col = next((j for j, x in labels.items() if "%" in x), None)

    indicators: list[Indicator] = []
    role = ""
    for rnum, row in enumerate(rows[start:], start=start + 1):
        r = str(cell(row, c_role) or "").strip()
        if r:
            role = r
        name = str(cell(row, c_name) or "").strip()
        if not name:
            continue
        kind, money = _kind(name)
        facts = [to_num(cell(row, w.col)) for w in weeks]
        pcts = [to_pct(cell(row, w.pct_col)) if w.pct_col is not None else None for w in weeks]
        indicators.append(Indicator(
            role or "—", name, to_num(cell(row, c_plan)), facts, kind, money, rnum, pcts,
        ))
    ps = PlanSheet(title, month, year, weeks, indicators, issues)
    issues += _pct_check(ps)
    return ps


def _pct_check(ps: "PlanSheet") -> list[str]:
    """Сверка нашей суммы фактов с колонкой «% накоп.» последней заполненной недели."""
    cw = ps.current_week
    if cw is None:
        return []
    out = []
    for ind in ps.indicators:
        if ind.kind != "sum" or not ind.plan:
            continue
        filled = [(i, x) for i, x in enumerate(ind.facts[: cw + 1]) if x is not None]
        if not filled:
            continue
        last_i = filled[-1][0]
        pct = ind.pcts[last_i] if last_i < len(ind.pcts) else None
        if pct is None:
            continue
        ours = sum(x for _, x in filled)
        theirs = pct * ind.plan
        where = f"«{ps.title}», {ind.role} «{ind.name}» (строка {ind.row})"
        if is_cumulative(ind, cw):
            out.append(
                f"{where}: факты внесены нарастающим итогом (последний {filled[-1][1]:g} совпадает "
                f"с «% накоп.»), бот берёт последнее значение, а не сумму недель."
            )
        elif abs(ours - theirs) > _tolerance(ind.plan):
            out.append(
                f"{where}: сумма фактов по неделям {ours:g}, а «% накоп.» даёт ≈{theirs:g} "
                f"({pct * 100:.0f}%). Проверьте, как вносятся факты."
            )
    return out


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
    cumulative: bool = False  # факты внесены нарастающим итогом — взяли последний


def _tolerance(plan: float) -> float:
    return max(0.5, abs(plan) * 0.02)


def is_cumulative(ind: Indicator, upto_week: int | None) -> bool:
    """Факты внесены нарастающим итогом?

    Да, если колонка «% накоп.» последней заполненной недели совпадает с
    последним фактом, а не с суммой фактов по неделям.
    """
    if ind.kind != "sum" or not ind.plan or upto_week is None:
        return False
    filled = [(i, x) for i, x in enumerate(ind.facts[: upto_week + 1]) if x is not None]
    if len(filled) < 2:
        return False
    last_i, last = filled[-1]
    pct = ind.pcts[last_i] if last_i < len(ind.pcts) else None
    if pct is None:
        return False
    implied = pct * ind.plan
    total = sum(x for _, x in filled)
    tol = _tolerance(ind.plan)
    return abs(last - implied) <= tol < abs(total - implied)


def evaluate(ind: Indicator, upto_week: int | None, pace: float) -> Result:
    weeks = ind.facts[: (upto_week + 1) if upto_week is not None else 0]
    filled = [x for x in weeks if x is not None]
    cumulative = False
    if ind.kind == "computed":
        # Стоимость лида: не суммируется — среднее по заполненным неделям.
        fact = sum(filled) / len(filled) if filled else None
    elif is_cumulative(ind, upto_week):
        fact, cumulative = filled[-1], True
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
    return Result(ind, fact, pct, status, cumulative)


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
