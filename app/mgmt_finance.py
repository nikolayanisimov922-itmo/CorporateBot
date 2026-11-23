"""«📈 Управление → 💵 Финансы»: разбор финансовой таблицы и тексты экранов.

Источник — зеркало «Финансы - для бота» таблицы «ДДС ОАЭ 2026» (Apps Script
deploy/sync_finance.gs копирует все листы раз в 15 минут; лист «_обновлено» —
время копии). Только чтение, всё считает код, без ИИ. Все суммы — AED.

Листы и что из них берём:
  «итоги / панель управления» — остатки по счетам, депозиты, выручка/расходы/
      прибыль текущего месяца, статьи расходов по месяцам, дебиторка, кредиторка;
      столбцы B…M = январь…декабрь, подписи строк в столбце A.
  «pl» — P&amp;L закрытых месяцев (выручка, валовая, чистая прибыль, налоги).
  «ФОТ_детально» — ЗП и KPI по людям и месяцам.
  «кредиторка» — договоры с подрядчиками: сумма по договору и выплачено.
  «маржинальность по направлениям» — дизайн / ремонт / комплектация.
  «ддс_<месяц>» — операции (для сравнения с прошлым месяцем на ту же дату и
      проверки ошибок ввода); «справочник» — какие статьи доходные, какие расходные.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field

from app.expenses import MONTHS_RU
from app.management_data import find_title, norm, to_date, to_num

e = html.escape

STAMP_SHEET = "_обновлено"
STALE_AFTER = dt.timedelta(hours=1)

MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
MON_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

# Доходные статьи, которые НЕ выручка (деньги клиентов на закупки, наши деньги,
# внутренние переводы): «10. Внесение собственных средств», «11–13. Депозит на
# закупку…», «15. Ввод алана», «16. Возвратные депозиты (доход)».
NOT_REVENUE_INCOME = {10, 11, 12, 13, 15, 16}
# Расходные статьи, которые не операционные расходы: закупки за счёт депозитов
# клиентов (52–54), вывод средств (44, 55, 57), возвраты депозитов (59, 61).
NOT_OPEX = {44, 52, 53, 54, 55, 57, 59, 61}
PURCHASES = {52, 53, 54}

DEPT_ORDER = ["Дизайн", "Ремонт", "Комплектация", "Продажи", "Маркетинг", "Администрация", "Не распределено"]


# --- форматирование -------------------------------------------------------------

def money(x: float | None, sign: bool = False) -> str:
    """12 579 951 → «12,58 млн», 640 210 → «640 тыс», 450 → «450». AED подразумевается."""
    if x is None:
        return "—"
    s = "−" if x < 0 else ("+" if sign and x > 0 else "")
    a = abs(x)
    if a >= 1_000_000:
        body = f"{a / 1_000_000:.2f}".replace(".", ",") + " млн"
    elif a >= 1000:
        body = f"{round(a / 1000):,}".replace(",", " ") + " тыс"
    else:
        body = f"{round(a)}"
    return s + body


def pct(x: float | None, sign: bool = False) -> str:
    if x is None:
        return "—"
    v = round(x * 100)
    return ("−" if v < 0 else ("+" if sign and v > 0 else "")) + f"{abs(v)}%"


def _code(label) -> int | None:
    m = re.match(r"\s*(\d{1,2})\b", str(label or ""))
    return int(m.group(1)) if m else None


def _is_err(v) -> bool:
    return isinstance(v, str) and v.strip().startswith("#") and v.strip().endswith(("!", "A", "?"))


def _month_of_header(v, pos: int) -> int:
    """Месяц столбца по заголовку («26.11.2026», «07/26»), иначе по позиции."""
    d = to_date(v)
    if d:
        return d.month
    m = re.match(r"^\s*(\d{1,2})\s*/\s*\d{2,4}\s*$", str(v or ""))
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1))
    return pos


# --- разбор листов ----------------------------------------------------------------

@dataclass
class Grid:
    """Лист «подпись в A + столбец на каждый месяц»: [(подпись, {месяц: значение})]."""

    rows: list[tuple[str, dict[int, object]]] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)  # нормализованная → как в таблице

    def find(self, label: str, exact: bool = False) -> dict[int, object]:
        n = norm(label)
        for lab, vals in self.rows:
            if (lab == n) if exact else lab.startswith(n):
                return vals
        return {}

    def num(self, label: str, month: int, exact: bool = False) -> float | None:
        return to_num(self.find(label, exact).get(month))

    def label(self, n: str) -> str:
        return self.labels.get(n, n)


def parse_grid(rows: list[list]) -> Grid:
    """Столбцы B…M — месяцы (по заголовку в строке 1, иначе по порядку)."""
    g = Grid()
    if not rows:
        return g
    head = rows[0]
    cols = {i: _month_of_header(head[i] if i < len(head) else None, i) for i in range(1, 13)}
    for r in rows[1:]:
        if not r or not str(r[0]).strip():
            continue
        n = norm(r[0])
        vals = {cols[i]: r[i] for i in range(1, 13) if i < len(r) and r[i] not in ("", None)}
        g.rows.append((n, vals))
        g.labels.setdefault(n, str(r[0]).strip())
    return g


@dataclass
class Person:
    name: str
    dept: str
    kind: str  # "zp" или "kpi"
    by_month: dict[int, float]


def dept_of(name: str) -> str:
    """Отдел по имени/должности из «ФОТ_детально» (должность — в скобках)."""
    n = norm(name)
    if n.startswith("kpi"):
        if "продаж" in n:
            return "Продажи"
        if "комплект" in n:
            return "Комплектация"
        if "прораб" in n:
            return "Ремонт"
        if "дизайн" in n:
            return "Дизайн"
        if "hr" in n or "финансист" in n:
            return "Администрация"
        return "Не распределено"
    if any(k in n for k in ("ilia", "илья", "ева (проджект)")):
        return "Дизайн"
    if any(k in n for k in ("tetiana", "татьяна")):
        return "Ремонт"
    if any(k in n for k in ("маркетинг", "таргет", "смм", "smm", "графическ", "продюсер")):
        return "Маркетинг"
    if any(k in n for k in ("роп", "продаж")):
        return "Продажи"
    if "комплект" in n:
        return "Комплектация"
    if any(k in n for k in ("прораб", "стройк", "ремонт")):
        return "Ремонт"
    if any(k in n for k in ("дизайн", "проектировщ", "визуализ", "3d")):
        return "Дизайн"
    if any(k in n for k in ("ceo", "(ба)", "финансист", "водитель", "бухгалт")) or n.startswith("hr") or " hr " in f" {n} ":
        return "Администрация"
    return "Не распределено"


@dataclass
class Payroll:
    months: list[int]
    people: list[Person]
    total_zp: dict[int, float]
    total_kpi: dict[int, float]

    def dept_totals(self, m: int) -> dict[str, tuple[float, float]]:
        out: dict[str, list[float]] = {}
        for p in self.people:
            v = p.by_month.get(m)
            if not v:
                continue
            t = out.setdefault(p.dept, [0.0, 0.0])
            t[0 if p.kind == "zp" else 1] += v
        return {d: (z, k) for d, (z, k) in out.items()}


def parse_payroll(rows: list[list]) -> Payroll:
    if not rows:
        return Payroll([], [], {}, {})
    months = {}
    for i, h in enumerate(rows[0]):
        hn = norm(h)
        for k, mname in enumerate(MONTHS_RU):
            if hn == norm(mname):
                months[i] = k + 1
    people, total_zp, total_kpi = [], {}, {}
    for r in rows[1:]:
        if not r or not str(r[0]).strip():
            continue
        name = str(r[0]).strip()
        vals = {m: to_num(r[i]) for i, m in months.items() if i < len(r) and to_num(r[i]) is not None}
        n = norm(name)
        if n.startswith("итого зп"):
            total_zp = vals
        elif n.startswith("итого kpi"):
            total_kpi = vals
        else:
            kind = "kpi" if n.startswith("kpi") else "zp"
            people.append(Person(name, dept_of(name), kind, vals))
    return Payroll(sorted(set(months.values())), people, total_zp, total_kpi)


@dataclass
class Payable:
    project: str
    contractor: str
    contract: float
    paid: float

    @property
    def left(self) -> float:
        return self.contract - self.paid


def parse_payables(rows: list[list]) -> tuple[list[Payable], float | None]:
    out, total = [], None
    for r in rows[1:]:
        if not r:
            continue
        proj = str(r[0]).strip() if r else ""
        c = to_num(r[2]) if len(r) > 2 else None
        p = to_num(r[3]) if len(r) > 3 else None
        if norm(proj) == "итого":
            total = (c or 0) - (p or 0)
            continue
        if c:
            out.append(Payable(proj, str(r[1]).strip() if len(r) > 1 and r[1] else "—", c, p or 0))
    return out, total


@dataclass
class Op:
    day: dt.date
    article: str
    income: float
    expense: float


def parse_dds(rows: list[list]) -> list[Op]:
    ops = []
    for r in rows[1:]:
        if len(r) < 2:
            continue
        d = to_date(r[0])
        if not d or not str(r[1]).strip():
            continue
        inc = to_num(r[2]) if len(r) > 2 else None
        exp = to_num(r[3]) if len(r) > 3 else None
        ops.append(Op(d, str(r[1]).strip(), inc or 0, exp or 0))
    return ops


def dds_sheet(data: dict, month: int) -> list[list]:
    t = find_title(list(data), f"ддс_{MONTHS_RU[month - 1].lower()}")
    return data.get(t, []) if t else []


@dataclass
class Finance:
    today: dt.date
    itogi: Grid
    pl: Grid
    marg: Grid
    payroll: Payroll
    payables: list[Payable]
    payables_total: float | None
    income_articles: set[str]
    expense_articles: set[str]
    data: dict
    stamp: str = ""
    stamp_at: dt.datetime | None = None

    @property
    def cur(self) -> int:
        return self.today.month

    # --- общие величины ---
    def balance_month(self) -> int:
        """Последний месяц (не позже текущего), где заполнен «ОСТАТОК»."""
        vals = self.itogi.find("остаток (на последний день")
        for m in range(self.cur, 0, -1):
            if to_num(vals.get(m)):
                return m
        return self.cur

    def closed_months(self) -> list[int]:
        """Закрытые месяцы P&amp;L (есть чистая прибыль, раньше текущего)."""
        vals = self.pl.find("чистая прибыль")
        return [m for m in range(1, self.cur) if to_num(vals.get(m)) is not None]

    def opex_avg(self, n: int = 3) -> float | None:
        vals = self.itogi.find("расход без вывода")
        ms = [m for m in range(self.cur - 1, 0, -1) if to_num(vals.get(m))][:n]
        if not ms:
            return None
        return sum(to_num(vals[m]) for m in ms) / len(ms)

    def expense_items(self, m: int) -> list[tuple[str, float]]:
        """Статьи расходов «итогов» за месяц (между «РАСХОД ИТОГО» и «ЗП предварительно»)."""
        out, inside = [], False
        for lab, vals in self.itogi.rows:
            if lab.startswith("расход итого"):
                inside = True
                continue
            if lab.startswith("зп предварительно"):
                break
            if inside and _code(lab) is not None:
                v = to_num(vals.get(m))
                if v:
                    out.append((self.itogi.label(lab), v))
        return out

    def income_items(self, m: int) -> list[tuple[str, float]]:
        out, inside = [], False
        for lab, vals in self.itogi.rows:
            if lab.startswith("выручка итого"):
                inside = True
                continue
            if inside:
                if _code(lab) is None:
                    break
                v = to_num(vals.get(m))
                if v:
                    out.append((self.itogi.label(lab), v))
        return out


def parse_finance(data: dict, today: dt.date, tz: str | None = None) -> Finance:
    def sheet(*names):
        for n in names:
            t = find_title(list(data), n)
            if t:
                return data[t]
        # «итоги / панель управления» — допускаем любое название, начинающееся с «итоги»
        for t in data:
            if norm(t).startswith(norm(names[0]).split()[0]):
                return data[t]
        return []

    ref = sheet("справочник")
    inc, exp = set(), set()
    for r in ref[1:]:
        if len(r) > 0 and str(r[0]).strip():
            exp.add(norm(r[0]))
        if len(r) > 1 and str(r[1]).strip():
            inc.add(norm(r[1]))
    payables, ptotal = parse_payables(sheet("кредиторка"))
    stamp_rows = data.get(find_title(list(data), STAMP_SHEET) or "", [])
    stamp = str(stamp_rows[0][1]).strip() if stamp_rows and len(stamp_rows[0]) > 1 else ""
    f = Finance(
        today=today,
        itogi=parse_grid(sheet("итоги / панель управления")),
        pl=parse_grid(sheet("pl")),
        marg=parse_grid(sheet("маржинальность по направлениям")),
        payroll=parse_payroll(sheet("ФОТ_детально")),
        payables=payables,
        payables_total=ptotal,
        income_articles=inc,
        expense_articles=exp,
        data=data,
        stamp=stamp,
    )
    f.stamp_at = _stamp_time(stamp, tz)
    return f


def _stamp_time(stamp: str, tz: str | None) -> dt.datetime | None:
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})", stamp or "")
    if not m or not tz:
        return None
    try:
        from zoneinfo import ZoneInfo

        d, mo, y, h, mi = (int(x) for x in m.groups())
        return dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz))
    except Exception:  # noqa: BLE001 — неизвестный пояс и т.п.
        return None


# --- проверки: что не так в таблице ---------------------------------------------------

def warnings(f: Finance, now: dt.datetime) -> list[str]:
    out = []
    if f.stamp_at and now - f.stamp_at > STALE_AFTER:
        out.append(f"Копия таблицы не обновлялась с {f.stamp} — проверьте скрипт копирования.")
    bm = f.balance_month()
    for name in ("Р/С", "Наличные", "Карта", "Криптовалюта", "Алана"):
        v = f.itogi.num(name, bm, exact=True)
        if v is not None and v < 0:
            out.append(f"Отрицательный остаток «{name}»: {money(v)}.")
    # Ошибки ввода в ДДС текущего месяца: доход по расходной статье и наоборот.
    for op in parse_dds(dds_sheet(f.data, f.cur)):
        a = norm(op.article)
        if op.income and a in f.expense_articles and a not in f.income_articles:
            out.append(
                f"ДДС {op.day:%d.%m}: доход {money(op.income)} записан по расходной статье «{e(op.article)}»."
            )
        if op.expense and a in f.income_articles and a not in f.expense_articles:
            out.append(
                f"ДДС {op.day:%d.%m}: расход {money(op.expense)} записан по доходной статье «{e(op.article)}»."
            )
    # Ошибки формул (#REF! и т.п.) в итогах и P&amp;L за текущий и прошлые месяцы.
    errs = []
    for title, g in (("итоги", f.itogi), ("pl", f.pl)):
        for lab, vals in g.rows:
            for m, v in vals.items():
                if m <= f.cur and _is_err(v):
                    errs.append(f"«{title}» → «{e(g.label(lab))}» ({MON_SHORT[m - 1]}): {e(str(v))}")
    if errs:
        out.append("Ошибки формул в таблице: " + "; ".join(errs[:3]) + (f" и ещё {len(errs) - 3}" if len(errs) > 3 else ""))
    # Дебиторка не меняется 3 месяца подряд — похоже, её не обновляют.
    deb = f.itogi.find("дебиторская задолженность итого")
    seq = [to_num(deb.get(m)) for m in range(bm - 2, bm + 1)]
    if all(v is not None for v in seq) and len(set(round(v) for v in seq)) == 1:
        out.append(f"Дебиторка одинаковая 3 месяца подряд ({money(seq[-1])}) — похоже, её не обновляют.")
    over = [p for p in f.payables if p.left < -1]
    if over:
        out.append(
            "Переплата подрядчикам сверх договора: "
            + "; ".join(f"{e(p.contractor)} — {money(-p.left)}" for p in over[:3])
        )
    m_dep = max((m for m in range(1, f.cur + 1) if f.itogi.num("депозиты траты по нашим", m) is not None
                 and f.itogi.num("депозиты траты по данным комплект", m) is not None), default=None)
    if m_dep:
        ours = f.itogi.num("депозиты траты по нашим", m_dep)
        theirs = f.itogi.num("депозиты траты по данным комплект", m_dep)
        if ours and abs(ours - theirs) > 0.05 * ours:
            out.append(
                f"Траты по депозитам за {MONTHS_RU[m_dep - 1].lower()} не сходятся: у финансов {money(ours)}, "
                f"у комплектаторов {money(theirs)} (разница {money(ours - theirs)})."
            )
    return out


# --- экраны -----------------------------------------------------------------------------

def _head(title: str) -> str:
    return f"💵 <b>{title}</b> · суммы в AED"


def _month_name(m: int) -> str:
    return MONTHS_RU[m - 1]


def summary_text(f: Finance, now: dt.datetime) -> str:
    bm, m = f.balance_month(), f.cur
    total = f.itogi.num("остаток (на последний день", bm)
    deps = f.itogi.num("депозиты", bm, exact=True)
    change = f.itogi.num("изменение на счетах", bm)
    free = total - deps if total is not None and deps is not None else None
    deb = f.itogi.num("дебиторская задолженность итого", bm)
    cred = f.itogi.num("кредиторская задолженность итого", bm)
    rev = f.itogi.num("выручка без собс", m)
    opex = f.itogi.num("расход без вывода", m)
    profit = f.itogi.num("прибыль (с учётом комплектации)", m)
    if profit is None and rev is not None and opex is not None:
        profit = rev - opex
    lines = [_head("Финансы — кратко"), ""]
    lines.append(f"💰 <b>Деньги всего: {money(total)}</b>" + (f" (за месяц {money(change, True)})" if change is not None else ""))
    if bm != m:
        lines.append(f"   <i>остатки за {MONTHS_RU[bm - 1].lower()} — за {MONTHS_RU[m - 1].lower()} ещё не внесены</i>")
    lines.append(f"   из них депозиты клиентов: {money(deps)}")
    lines.append(f"   свободные деньги компании: <b>{money(free)}</b>")
    lines.append("")
    lines.append(f"🧾 Нам должны (дебиторка): {money(deb)}")
    lines.append(f"🧾 Мы должны (кредиторка): {money(cred)}")
    if deb is not None and cred is not None:
        lines.append(f"   чистая позиция: {money(deb - cred, True)}")
    lines.append("")
    lines.append(f"📅 <b>{_month_name(m)} на {f.today.day} {MONTHS_GEN[m - 1]}</b>")
    if rev is None and opex is None:
        lines.append("   операций за месяц в таблице пока нет")
    else:
        lines.append(f"   выручка (поступления по проектам): {money(rev)}")
        lines.append(f"   расходы: {money(opex)}")
        lines.append(f"   прибыль: <b>{money(profit)}</b>")
    closed = f.closed_months()
    if closed:
        lm = closed[-1]
        lrev, lnp = f.pl.num("выручка", lm, exact=True), f.pl.num("чистая прибыль", lm)
        lines.append("")
        lines.append(f"📆 <b>{_month_name(lm)} (закрыт)</b>")
        lines.append(
            f"   выручка (P&amp;L): {money(lrev)} · чистая прибыль: <b>{money(lnp)}</b>"
            + (f" ({pct(lnp / lrev)})" if lrev and lnp is not None else "")
        )
    pm = m if m in f.payroll.total_zp else (f.payroll.months[-1] if f.payroll.months else None)
    if pm:
        zp, kpi = f.payroll.total_zp.get(pm), f.payroll.total_kpi.get(pm)
        lines.append("")
        lines.append(f"👥 ФОТ за {MONTHS_RU[pm - 1].lower()}: ЗП {money(zp)} + KPI {money(kpi)} = <b>{money((zp or 0) + (kpi or 0))}</b>")
    w = warnings(f, now)
    if w:
        lines += ["", "⚠️ <b>Обратить внимание</b>"] + [f"• {x}" for x in w[:3]]
        if len(w) > 3:
            lines.append(f"… и ещё {len(w) - 3} — см. «📋 Расширенная сводка → ⚠️ Обратить внимание»")
    return "\n".join(lines)


def money_text(f: Finance) -> str:
    bm = f.balance_month()
    prev = bm - 1
    lines = [_head(f"Деньги и счета · {_month_name(bm)}"), ""]
    total = f.itogi.num("остаток (на последний день", bm)
    for name in ("Р/С", "Наличные", "Карта", "Криптовалюта", "Алана"):
        v = f.itogi.num(name, bm, exact=True)
        pv = f.itogi.num(name, prev, exact=True) if prev >= 1 else None
        share = f" · {pct(v / total)}" if v and total and v / total >= 0.01 else ""
        ch = f" ({money(v - pv, True)})" if v is not None and pv is not None and round(v - pv) else ""
        lines.append(f"• {name}: <b>{money(v)}</b>{ch}{share}")
    lines.append(f"<b>Итого: {money(total)}</b>")
    deps = f.itogi.num("депозиты", bm, exact=True)
    if total is not None and deps is not None:
        free = total - deps
        lines += ["", f"🏦 Депозиты клиентов: {money(deps)}", f"✅ Свободные деньги компании: <b>{money(free)}</b>"]
        avg = f.opex_avg()
        if avg:
            lines.append(
                f"🛟 Запас прочности: ≈ <b>{free / avg:.1f}".replace(".", ",") + "</b> мес."
                + f"\n   (свободные деньги ÷ средние расходы за 3 мес. {money(avg)})"
            )
    crypto = f.itogi.num("криптовалюта", bm, exact=True)
    if crypto and total and crypto / total > 0.5:
        lines.append(f"⚠️ {pct(crypto / total)} всех денег — в криптовалюте.")
    hist = [(mm, f.itogi.num("остаток (на последний день", mm)) for mm in range(1, bm + 1)]
    hist = [(mm, v) for mm, v in hist if v]
    if len(hist) > 1:
        lines += ["", "<b>Остаток по месяцам</b>"]
        for mm, v in hist[-6:]:
            lines.append(f"• {MON_SHORT[mm - 1]}: {money(v)}")
    return "\n".join(lines)


def pl_text(f: Finance) -> str:
    closed = f.closed_months()
    lines = [_head("Прибыль по месяцам (P&amp;L)"), ""]
    if not closed:
        return "\n".join(lines + ["Закрытых месяцев в «pl» пока нет."])
    lines.append("<i>месяц: выручка · чистая прибыль · маржа</i>")
    ytd_rev = ytd_np = 0.0
    rows = []
    for m in closed:
        rev, np_ = f.pl.num("выручка", m, exact=True), f.pl.num("чистая прибыль", m)
        ytd_rev += rev or 0
        ytd_np += np_ or 0
        rows.append((m, rev, np_))
        lines.append(
            f"• {MON_SHORT[m - 1]}: {money(rev)} · <b>{money(np_)}</b> · {pct(np_ / rev) if rev else '—'}"
        )
    m = f.cur
    rev, profit = f.itogi.num("выручка без собс", m), f.itogi.num("прибыль (с учётом комплектации)", m)
    if rev is not None or profit is not None:
        lines.append(f"• {MON_SHORT[m - 1]} (идёт): {money(rev)} · {money(profit)} · —")
    lines += ["", f"<b>С начала года</b> ({len(closed)} мес.): выручка {money(ytd_rev)}, чистая прибыль <b>{money(ytd_np)}</b>"
              + (f" ({pct(ytd_np / ytd_rev)})" if ytd_rev else "")]
    valid = [(m, r, p) for m, r, p in rows if p is not None]
    if valid:
        best = max(valid, key=lambda x: x[2])
        worst = min(valid, key=lambda x: x[2])
        lines.append(f"Лучший месяц: {MONTHS_RU[best[0] - 1].lower()} ({money(best[2])})")
        lines.append(f"Худший месяц: {MONTHS_RU[worst[0] - 1].lower()} ({money(worst[2])})")
    lm = closed[-1]
    gp, ebt = f.pl.num("валовая прибыль", lm), f.pl.num("прибыль до налогов", lm)
    lrev = f.pl.num("выручка", lm, exact=True)
    if lrev:
        lines += ["", f"<b>{_month_name(lm)} подробно</b>",
                  f"• Выручка: {money(lrev)}",
                  f"• Валовая прибыль: {money(gp)} ({pct(gp / lrev) if gp is not None else '—'})",
                  f"• Прибыль до налогов: {money(ebt)}",
                  f"• Чистая прибыль: {money(f.pl.num('чистая прибыль', lm))}"]
        for lab in ("Дизайн", "Стройка", "Комплектация"):
            v = f.pl.num(lab, lm, exact=True)
            if v:
                lines.append(f"   выручка «{lab}»: {money(v)}")
    lines += ["", "<i>Выручка в P&amp;L включает работу комплектации за счёт депозитов, поэтому она больше, "
                  "чем «поступления по проектам» текущего месяца.</i>"]
    return "\n".join(lines)


def _ops_until(ops: list[Op], year: int, month: int, day: int) -> list[Op]:
    return [o for o in ops if o.day.year == year and o.day.month == month and o.day.day <= day]


def _revenue(ops: list[Op], inc_articles: set[str]) -> float:
    return sum(o.income for o in ops if norm(o.article) in inc_articles and _code(o.article) not in NOT_REVENUE_INCOME)


def _opex(ops: list[Op], exp_articles: set[str]) -> float:
    return sum(o.expense for o in ops if norm(o.article) in exp_articles and _code(o.article) not in NOT_OPEX)


def month_text(f: Finance) -> str:
    m = f.cur
    lines = [_head(f"{_month_name(m)} на {f.today.day} {MONTHS_GEN[m - 1]}"), ""]
    rev = f.itogi.num("выручка без собс", m)
    opex = f.itogi.num("расход без вывода", m)
    profit = f.itogi.num("прибыль (с учётом комплектации)", m)
    lines.append(f"📥 Выручка (поступления по проектам): <b>{money(rev)}</b>")
    inc = f.income_items(m)
    for lab, v in sorted((x for x in inc if _code(x[0]) not in NOT_REVENUE_INCOME), key=lambda x: -x[1]):
        lines.append(f"   • {e(lab)}: {money(v)}")
    other = [(lab, v) for lab, v in inc if _code(lab) in NOT_REVENUE_INCOME]
    if other:
        lines.append("   <i>не выручка: " + "; ".join(f"{e(lab)} {money(v)}" for lab, v in other) + "</i>")
    lines.append("")
    lines.append(f"📤 Расходы (без закупок по депозитам и вывода средств): <b>{money(opex)}</b>")
    items = [x for x in f.expense_items(m) if _code(x[0]) not in NOT_OPEX]
    for lab, v in sorted(items, key=lambda x: -x[1])[:5]:
        lines.append(f"   • {e(lab)}: {money(v)}")
    zp_pre = f.itogi.num("зп предварительно", m)
    if zp_pre:
        lines.append(f"   <i>в т.ч. ЗП начислена предварительно: {money(zp_pre)}</i>")
    purch = sum(v for lab, v in f.expense_items(m) if _code(lab) in PURCHASES)
    if purch:
        lines.append(f"   <i>закупки за счёт депозитов клиентов: {money(purch)}</i>")
    lines += ["", f"💼 <b>Прибыль: {money(profit)}</b>"]
    # Сравнение с прошлым месяцем на ту же дату — по операциям ДДС.
    py, pm = (f.today.year, m - 1) if m > 1 else (f.today.year - 1, 12)
    cur_ops = _ops_until(parse_dds(dds_sheet(f.data, m)), f.today.year, m, f.today.day)
    prev_ops = _ops_until(parse_dds(dds_sheet(f.data, pm)), py, pm, f.today.day)
    if cur_ops and prev_ops:
        r1, r0 = _revenue(cur_ops, f.income_articles), _revenue(prev_ops, f.income_articles)
        x1, x0 = _opex(cur_ops, f.expense_articles), _opex(prev_ops, f.expense_articles)
        d = f.today.day
        lines += ["", f"📊 <b>1–{d} {MONTHS_GEN[m - 1]} vs 1–{d} {MONTHS_GEN[pm - 1]}</b> (по ДДС)",
                  f"• выручка: {money(r1)} vs {money(r0)}" + (f" ({pct(r1 / r0 - 1, True)})" if r0 else ""),
                  f"• расходы: {money(x1)} vs {money(x0)}" + (f" ({pct(x1 / x0 - 1, True)})" if x0 else ""),
                  "<i>по ДДС, без начисленной ЗП — поэтому могут отличаться от строк выше</i>"]
    return "\n".join(lines)


def debts_text(f: Finance) -> str:
    bm = f.balance_month()
    lines = [_head("Долги"), ""]
    deb = f.itogi.num("дебиторская задолженность итого", bm)
    lines.append(f"🟢 <b>Нам должны (дебиторка): {money(deb)}</b>")
    for lab in ("ДИЗАЙН", "СТРОЙКА", "КОМПЛЕКТАЦИЯ"):
        v = f.itogi.num(f"дебиторская задолженность {lab}", bm)
        if v is None:
            # ищем последнее заполненное значение
            vals = f.itogi.find(f"дебиторская задолженность {lab}")
            last = max((mm for mm in vals if mm <= bm and to_num(vals[mm]) is not None), default=None)
            if last:
                v = to_num(vals[last])
                lines.append(f"   • {lab.capitalize()}: {money(v)} <i>(данные за {MONTHS_RU[last - 1].lower()})</i>")
            continue
        lines.append(f"   • {lab.capitalize()}: {money(v)}")
    cred = f.itogi.num("кредиторская задолженность итого", bm)
    lines += ["", f"🔴 <b>Мы должны (кредиторка): {money(cred)}</b>"]
    by: dict[str, float] = {}
    for p in f.payables:
        if p.left > 1:
            by[p.contractor] = by.get(p.contractor, 0) + p.left
    for c, v in sorted(by.items(), key=lambda x: -x[1]):
        lines.append(f"   • {e(c)}: {money(v)}")
    if by:
        lines.append("")
        lines.append("<b>По проектам (осталось заплатить)</b>")
        for p in sorted((p for p in f.payables if p.left > 1), key=lambda p: -p.left)[:8]:
            lines.append(f"   • {e(p.project[:40])} — {e(p.contractor)}: {money(p.left)} из {money(p.contract)}")
    over = [p for p in f.payables if p.left < -1]
    if over:
        lines += ["", "⚠️ <b>Выплачено больше договора</b>"]
        for p in over:
            lines.append(f"   • {e(p.project[:40])} — {e(p.contractor)}: +{money(-p.left)}")
    if deb is not None and cred is not None:
        lines += ["", f"⚖️ Чистая позиция: <b>{money(deb - cred, True)}</b>"]
    return "\n".join(lines)


def deposits_text(f: Finance) -> str:
    lines = [_head("Депозиты клиентов"), ""]
    bm = f.balance_month()
    lines.append(f"Остаток депозитов: <b>{money(f.itogi.num('депозиты', bm, exact=True))}</b>")
    lines += ["", "<i>месяц: внесено · потрачено · остаток</i>"]
    for m in range(max(1, f.cur - 4), f.cur + 1):
        inn = f.itogi.num("внесенные депозиты", m)
        out = f.itogi.num("траты по депозитам", m)
        rest = f.itogi.num("депозиты", m, exact=True)
        if inn is None and out is None and not rest:
            continue
        tail = " (идёт)" if m == f.cur else ""
        lines.append(f"• {MON_SHORT[m - 1]}{tail}: {money(inn)} · {money(out)} · {money(rest)}")
    m_dep = max((m for m in range(1, f.cur + 1) if f.itogi.num("депозиты траты по нашим", m) is not None
                 and f.itogi.num("депозиты траты по данным комплект", m) is not None), default=None)
    if m_dep:
        ours = f.itogi.num("депозиты траты по нашим", m_dep)
        theirs = f.itogi.num("депозиты траты по данным комплект", m_dep)
        lines += ["", f"🔍 <b>Сверка трат за {MONTHS_RU[m_dep - 1].lower()}</b>",
                  f"• по данным финансов: {money(ours)}",
                  f"• по данным комплектаторов: {money(theirs)}",
                  f"• разница: <b>{money(ours - theirs, True)}</b>"]
    return "\n".join(lines)


def payroll_text(f: Finance, m: int) -> str:
    pr = f.payroll
    lines = [_head(f"ФОТ · {_month_name(m)}"), ""]
    zp, kpi = pr.total_zp.get(m), pr.total_kpi.get(m)
    lines.append(f"ЗП: <b>{money(zp)}</b> · KPI: <b>{money(kpi)}</b> · всего: <b>{money((zp or 0) + (kpi or 0))}</b>")
    rev = f.pl.num("выручка", m, exact=True)
    if rev:
        lines.append(f"Доля ФОТ в выручке: {pct(((zp or 0) + (kpi or 0)) / rev)}")
    lines += ["", "<b>По отделам</b> <i>(ЗП + KPI)</i>"]
    totals = pr.dept_totals(m)
    for d in DEPT_ORDER:
        if d in totals:
            z, k = totals[d]
            lines.append(f"• {d}: <b>{money(z + k)}</b> (ЗП {money(z)} · KPI {money(k)})")
    s = sum(z + k for z, k in totals.values())
    if zp is not None and abs(s - (zp or 0) - (kpi or 0)) > 1:
        lines.append(f"<i>⚠️ сумма по людям ({money(s)}) не сходится с итогом таблицы</i>")
    hist = [mm for mm in pr.months if pr.total_zp.get(mm)]
    if len(hist) > 1:
        lines += ["", "<b>По месяцам</b> <i>(ЗП + KPI)</i>"]
        for mm in hist[-6:]:
            lines.append(f"• {MON_SHORT[mm - 1]}: {money((pr.total_zp.get(mm) or 0) + (pr.total_kpi.get(mm) or 0))}")
    return "\n".join(lines)


def payroll_people_text(f: Finance, m: int) -> str:
    lines = [_head(f"ФОТ по сотрудникам · {_month_name(m)}"), ""]
    for d in DEPT_ORDER:
        ps = [p for p in f.payroll.people if p.dept == d and p.by_month.get(m)]
        if not ps:
            continue
        lines.append(f"<b>{d}</b>")
        for p in sorted(ps, key=lambda p: (p.kind, -p.by_month[m])):
            mark = "KPI · " if p.kind == "kpi" else ""
            lines.append(f"• {mark}{e(p.name)}: {money(p.by_month[m])}")
        lines.append("")
    return "\n".join(lines).strip()


def directions_text(f: Finance) -> str:
    lines = [_head("Направления: доход и маржинальность"), ""]
    blocks = []
    for i, (lab, vals) in enumerate(f.marg.rows):
        for d in ("дизайн", "ремонт", "комплектация"):
            if lab.startswith(f"{d} доход"):
                marg = next((v for l2, v in f.marg.rows[i + 1:i + 3] if l2.startswith("маржинальность")), {})
                rev = next((v for l2, v in f.marg.rows[i + 1:i + 6] if l2 == "выручка"), {})
                blocks.append((d.capitalize(), vals, marg, rev))
    if not blocks:
        return "\n".join(lines + ["Лист «маржинальность по направлениям» пустой или не найден."])
    months = sorted({m for _, v, _, _ in blocks for m in v if to_num(v[m]) is not None})[-4:]
    lines.append("<i>месяц: выручка → доход направления (маржа)</i>")
    for name, inc, marg, rev in blocks:
        lines += ["", f"<b>{name}</b>"]
        for m in months:
            r, i_, mg = to_num(rev.get(m)), to_num(inc.get(m)), to_num(marg.get(m))
            if r is None and i_ is None:
                continue
            lines.append(f"• {MON_SHORT[m - 1]}: {money(r)} → {money(i_)} ({pct(mg)})")
    return "\n".join(lines)


def anomalies_text(f: Finance) -> str:
    lines = [_head("Аномалии расходов"), "",
             "<i>Статьи, где расход в 2+ раза выше среднего за 3 предыдущих месяца "
             "(без закупок по депозитам и вывода средств).</i>"]
    found = False
    for m in (f.cur, f.cur - 1):
        if m < 1:
            continue
        rows = []
        for lab, v in f.expense_items(m):
            if _code(lab) in NOT_OPEX:
                continue
            prev = [to_num(f.itogi.find(norm(lab), exact=True).get(mm)) for mm in range(m - 3, m) if mm >= 1]
            prev = [p for p in prev if p is not None]
            if not prev:
                continue
            avg = sum(prev) / len(prev)
            if (avg > 0 and v >= 2 * avg and v - avg >= 10_000) or (avg == 0 and v >= 20_000):
                rows.append((lab, v, avg))
        title = f"{_month_name(m)}" + (" (идёт)" if m == f.cur else "")
        lines += ["", f"<b>{title}</b>"]
        if not rows:
            lines.append("• аномалий нет")
            continue
        found = True
        for lab, v, avg in sorted(rows, key=lambda x: -(x[1] - x[2]))[:7]:
            ratio = ("в 10+ раз выше" if v / avg >= 10 else f"×{v / avg:.1f}".replace(".", ",")) if avg else "новая статья"
            lines.append(f"• {e(lab)}: <b>{money(v)}</b> (обычно {money(avg)}, {ratio})")
    if not found:
        lines.append("")
    return "\n".join(lines)


def taxes_text(f: Finance) -> str:
    lines = [_head("Налоги и вывод средств"), ""]
    closed = f.closed_months()
    corp = sum(f.pl.num("корпоративный налог", m) or 0 for m in closed)
    vat = sum(f.pl.num("vat", m, exact=True) or 0 for m in closed)
    lines.append(f"🏛 <b>Налоги с начала года</b> (по P&amp;L, {len(closed)} мес.)")
    lines.append(f"• Корпоративный налог: {money(corp)}")
    lines.append(f"• VAT: {money(vat)}")
    lines.append(f"• Итого: <b>{money(corp + vat)}</b>")
    lines += ["", "💸 <b>Вывод средств</b> <i>(месяц: вывод средств · на Алану)</i>",
              "<i>вывод = статьи «44. Вывод средств собственнику» + «57 Вывод средств»</i>"]
    tot_owner = tot_alana = 0.0
    for m in range(1, f.cur + 1):
        own = (f.itogi.num("44. вывод средств", m) or 0) + (f.itogi.num("57 вывод средств", m) or 0)
        alana = f.itogi.num("55. вывод на алану", m) or 0
        if not own and not alana:
            continue
        tot_owner += own
        tot_alana += alana
        tail = " (идёт)" if m == f.cur else ""
        lines.append(f"• {MON_SHORT[m - 1]}{tail}: {money(own)} · {money(alana)}")
    lines.append(f"<b>Всего:</b> вывод {money(tot_owner)} · на Алану {money(tot_alana)}")
    lines.append("<i>Данные о выводе в таблице есть с июля.</i>")
    return "\n".join(lines)


def warnings_text(f: Finance, now: dt.datetime) -> str:
    w = warnings(f, now)
    lines = [_head("Обратить внимание"), ""]
    lines += [f"• {x}" for x in w] if w else ["✅ Замечаний нет."]
    return "\n".join(lines)


def footer(f: Finance) -> str:
    """Когда скрипт последний раз скопировал основную таблицу."""
    if f.stamp_at:
        from app.expenses import DUBAI

        return f"🗂 копия таблицы от {f.stamp_at.astimezone(DUBAI):%d.%m %H:%M} (Дубай)"
    return f"🗂 копия таблицы: {e(f.stamp)}" if f.stamp else ""
