"""«📊 Планы»: разбор листов «ПЛАН <МЕСЯЦ>» и выполнение месячного плана (чистые функции).

Как устроен лист:
  • строка 1 — «Роль | Показатель | План на месяц (колонка C) | Неделя 01.10 - 02.10 | …»;
  • у КАЖДОГО отдела над его строками своя строка подписей недельного блока:
      – почти у всех: «План (недели) | Факт | % плана недели | % плана месяца (накоп.)»
        → факты — колонки E, I, M, Q, U; недельные планы (D, H, L, P, T) НЕ трогаем;
      – у маркетинга колонки объединены: «Факт | % плана месяца (накоп.)».
    Поэтому колонки факта и % определяются по подписям над каждым отделом, а не
    одни на весь лист.

Как считаем результат за месяц (накопительно, без разбивки по неделям):
  • главный маркер — итоговый % выполнения из таблицы (последняя колонка «% плана»
    в листе месяца); абсолютное число = % × план месяца (колонка C);
  • маркетинг — сумма фактов по неделям / план; стоимость лида — СРЕДНЕЕ по неделям
    против плана (меньше — лучше); бюджеты — сумма, «в рамках / превышен».
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
    start: int  # первая колонка блока недели
    end: int  # колонка после блока
    months: set = field(default_factory=set)  # месяцы из дат в заголовке


@dataclass
class Indicator:
    role: str
    name: str
    plan: float | None
    facts: list  # по неделям, None — не заполнено
    pcts: list  # «% плана месяца (накоп.)» из таблицы по неделям (доли), None — пусто
    kind: str  # "sum" | "inverse" | "computed"
    money: bool = False
    row: int = 0  # номер строки в таблице (для /mgmt_plan_raw)
    fact_cols: list = field(default_factory=list)
    pct_cols: list = field(default_factory=list)

    @property
    def marketing(self) -> bool:
        return "маркет" in norm(self.role)

    @property
    def table_pct(self) -> float | None:
        """Итоговый % выполнения из таблицы: последняя заполненная колонка «% накоп.»."""
        for p in reversed(self.pcts):
            if p is not None:
                return p
        return None


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


def _section_cols(
    row: list, weeks: list[Week], heads: list[str]
) -> list[tuple[int, int | None]] | None:
    """Строка подписей отдела → [(колонка «Факт», колонка «% накоп.»)] по неделям.

    None — если это не строка подписей (нет ни одного «Факт»). Колонка % — самая
    правая в блоке недели с «%» (кроме «% плана недели»): «% плана месяца (накоп.)»
    или итоговая «% плана» (её подпись может стоять только в 1-й строке листа).
    """
    out, found = [], False
    for w in weeks:
        fact = pct = None
        for j in range(w.start, w.end):
            x = norm(row[j]) if j < len(row) else ""
            top = heads[j] if j < len(heads) else ""
            if fact is None and x.startswith("факт"):
                fact = j
            for lab in (x, top):
                if "%" in lab and "недел" not in lab:
                    pct = j
        found = found or fact is not None
        out.append((fact if fact is not None else w.start, pct))
    return out if found else None


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

    starts = []
    for i, x in enumerate(heads):
        if i <= c_plan or not x:
            continue
        dates = _DATES.findall(x)
        if x.startswith("неделя") or dates:
            raw = str(rows[h][i]).strip()
            starts.append((i, raw.replace("Неделя", "").strip() or raw, {int(m) for _, m in dates}))
    width = max((len(r) for r in rows), default=0)
    weeks = [
        Week(label, s, starts[k + 1][0] if k + 1 < len(starts) else width, months)
        for k, (s, label, months) in enumerate(starts)
    ]
    foreign = [w.label for w in weeks if w.months and month not in w.months]
    if foreign:
        issues.append(
            f"«{title}»: даты недель не из этого месяца ({', '.join(foreign[:3])}) — "
            "похоже, лист скопирован с другого месяца"
        )

    cols = [(w.start, None) for w in weeks]
    indicators: list[Indicator] = []
    role = ""
    for rnum, row in enumerate(rows[h + 1:], start=h + 2):
        section = _section_cols(row, weeks, heads)
        r = str(cell(row, c_role) or "").strip()
        if section is not None:
            cols = section  # подписи нового отдела — дальше читаем по ним
            if r:
                role = r
            continue
        if r:
            role = r
        name = str(cell(row, c_name) or "").strip()
        if not name:
            continue
        kind, money = _kind(name)
        indicators.append(Indicator(
            role=role or "—",
            name=name,
            plan=to_num(cell(row, c_plan)),
            facts=[to_num(cell(row, f)) for f, _ in cols],
            pcts=[to_pct(cell(row, p)) if p is not None else None for _, p in cols],
            kind=kind,
            money=money,
            row=rnum,
            fact_cols=[f for f, _ in cols],
            pct_cols=[p for _, p in cols],
        ))
    ps = PlanSheet(title, month, year, weeks, indicators, issues)
    issues += _pct_check(ps)
    return ps


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


def evaluate(ind: Indicator, pace: float) -> Result:
    """Выполнение за месяц накопительно."""
    filled = [x for x in ind.facts if x is not None]
    if ind.kind == "computed":
        # Стоимость лида: не суммируется — среднее по заполненным неделям.
        fact = sum(filled) / len(filled) if filled else None
    else:
        fact = sum(filled) if filled else None
    if ind.plan in (None, 0):
        return Result(ind, fact, None, "⚪")
    if ind.kind in ("inverse", "computed"):
        if fact is None:
            return Result(ind, fact, None, "⚪")
        return Result(ind, fact, fact / ind.plan, "✅" if fact <= ind.plan else "⚠️")
    if not ind.marketing and ind.table_pct is not None:
        # Главный маркер — итоговый % из таблицы; абсолютное число — от него.
        pct = ind.table_pct
        fact = pct * ind.plan
        if not ind.money:
            fact = round(fact)  # штуки и люди — целым числом (66,7% от 12 → 8)
    else:
        pct = (fact or 0) / ind.plan
    lag = pace - pct
    status = "🟢" if lag <= 0 else ("🟡" if lag <= 0.15 else "🔴")
    return Result(ind, fact, pct, status)


def _pct_check(ps: PlanSheet) -> list[str]:
    """Для /mgmt_check: где сумма фактов не сходится с итоговым % таблицы."""
    out = []
    for ind in ps.indicators:
        if ind.marketing or ind.kind != "sum" or not ind.plan or ind.table_pct is None:
            continue
        filled = [x for x in ind.facts if x is not None]
        if not filled:
            continue
        ours = sum(filled)
        theirs = ind.table_pct * ind.plan
        if abs(ours - theirs) > max(0.5, abs(ind.plan) * 0.02):
            out.append(
                f"«{ps.title}», {ind.role} «{ind.name}» (строка {ind.row}): сумма фактов {ours:g}, "
                f"а итоговый % в таблице {ind.table_pct * 100:.1f}% (≈{theirs:g}) — бот показывает по %."
            )
    return out


def plan_query(ps: PlanSheet, role: str | None, today: dt.date) -> dict:
    """Для «💬 Спросить»: показатели листа (по отделу), накопительно за месяц."""
    pace = workdays_share(ps.year, ps.month, today)
    items = []
    for ind in ps.indicators:
        if role and norm(role) not in norm(ind.role):
            continue
        r = evaluate(ind, pace)
        items.append({
            "department": ind.role, "indicator": ind.name, "plan_month": ind.plan,
            "fact_month_to_date": round(r.fact, 2) if r.fact is not None else None,
            "percent": round(r.pct * 100, 1) if r.pct is not None else None,
            "status": r.status,
            "type": {"sum": "чем больше, тем лучше", "inverse": "бюджет: меньше — лучше",
                     "computed": "стоимость лида: среднее за месяц, меньше — лучше"}[ind.kind],
        })
    return {
        "sheet": ps.title,
        "month": f"{MONTHS_RU[ps.month - 1]} {ps.year}",
        "note": "факт накопительно за месяц; % — итоговый % выполнения из таблицы",
        "expected_pace_percent": round(pace * 100),
        "plan_filled": ps.has_plan,
        "indicators": items,
    }
