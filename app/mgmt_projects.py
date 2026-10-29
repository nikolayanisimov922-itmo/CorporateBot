"""«📁 Проекты»: разбор мастер-таблицы и расчёты (чистые функции, без сети).

Два источника — и у каждого своя роль:
  • «Общая таблица» — сводка по компании (всего / в работе / на паузе / по типам);
  • листы отделов («Отдел разработки» и т.д.) — всё, что про отдел и людей:
    сколько проектов в работе у отдела и у каждого сотрудника, м², деньги
    (контракт / оплачено / остаток). Отделы ведут эти листы сами, статусы и
    ответственные там — «официальные». Проект может стоять на листах двух
    отделов (комплектация + визуализации, напр. 387-03: Alina и Ilya) — тогда он
    идёт в зачёт обоим отделам и обоим исполнителям.
Листы «Загрузка …» не используем — их формулы расходятся с листами отделов.
Заголовки ищем по тексту, а не по номерам строк/колонок.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from app.management_data import (
    cell,
    col,
    find_header,
    get_sheet,
    norm,
    to_date,
    to_num,
)

DEV, REAL, KOMP, NOTYPE = "dev", "real", "komp", "none"
DEPT_RU = {DEV: "Разработка", REAL: "Реализация", KOMP: "Комплектация", NOTYPE: "Без типа"}
DEPT_EN = {DEV: "Design", REAL: "Construction", KOMP: "Procurement", NOTYPE: "No type"}
DEPTS = (DEV, REAL, KOMP)

ACTIVE, PAUSED, DONE, REFUSED, NEW, UNKNOWN = (
    "in_progress", "paused", "completed", "refused", "new", "unknown",
)

_STATUS = {
    "in progress": ACTIVE,
    "on pause": PAUSED,
    "pause": PAUSED,
    "completed": DONE,
    "the client refused": REFUSED,
    "rejections": REFUSED,
    "rejection": REFUSED,
    "refused": REFUSED,
    "new": NEW,
}
_TYPE = {
    "design project": DEV,
    "construction": REAL,
    "interior equipment": KOMP,
}
# Код проекта по суффиксу номера: 381-02 — дизайн, 381-03 — комплектация, 381-04 — ремонт.
_SUFFIX = {"02": DEV, "03": KOMP, "04": REAL}
_SUFFIX_RE = re.compile(r"\d-(\d{2})\b")
# «Не люди» в колонках ответственных.
_NOT_PEOPLE = {"without a project", "без проекта", ""}

DEPT_SHEET = {DEV: "Отдел разработки", REAL: "Отдел реализации", KOMP: "Отдел комплектации"}


def norm_status(v) -> str:
    return _STATUS.get(norm(v), UNKNOWN)


def dept_by_number(number: str) -> str:
    m = _SUFFIX_RE.search(number or "")
    return _SUFFIX.get(m.group(1), NOTYPE) if m else NOTYPE


def norm_type(v, number: str = "") -> tuple[str, bool]:
    """(отдел, взят ли он по коду проекта, потому что тип не заполнен)."""
    d = _TYPE.get(norm(v))
    if d:
        return d, False
    by_code = dept_by_number(number)
    return by_code, by_code != NOTYPE


def strip_number(name: str, number: str) -> str:
    """«361-02 Unit 202, …» → «Unit 202, …», если номер уже стоит в начале названия."""
    n = (name or "").strip()
    if number and n.startswith(number):
        return n[len(number):].lstrip(" ,.-—_")
    return n


@dataclass
class Project:
    """Строка «Общей таблицы»."""

    number: str
    name: str
    dept: str
    status: str
    stage: str = ""
    area: float | None = None
    revenue: float | None = None
    signed: dt.date | None = None
    plan_end: dt.date | None = None
    people: dict = field(default_factory=dict)  # роль → имя
    raw_status: str = ""
    raw_type: str = ""
    type_by_code: bool = False


@dataclass
class DeptRow:
    """Строка листа отдела."""

    dept: str
    number: str
    name: str
    status: str
    person: str
    area: float | None = None
    contract: float | None = None
    paid: float | None = None
    remaining: float | None = None
    signed: dt.date | None = None
    raw_type: str = ""


@dataclass
class ProjectsData:
    projects: list[Project]
    dept_rows: dict  # отдел → [DeptRow]
    issues: list[str]


def _txt(v) -> str:
    return str(v).strip() if v is not None else ""


def parse_general(rows: list[list], issues: list[str]) -> list[Project]:
    hit = find_header(rows, ["project number", "project status"])
    if not hit:
        issues.append("«Общая таблица»: не нашёл строку заголовков (Project number / Project Status)")
        return []
    h, heads = hit
    c = {
        "num": col(heads, "project number"),
        "name": col(heads, "project name"),
        "area": col(heads, "area, m2", "area m2", "area"),
        "type": col(heads, "project type"),
        "status": col(heads, "project status"),
        "stage": col(heads, "project stage"),
        "designer": col(heads, "responsible designer"),
        "architect": col(heads, "responsible architect"),
        "visualizer": col(heads, "responsible visualizer"),
        "pm": col(heads, "project manager/designer", "project manager"),
        "foreman": col(heads, "responsible foreman"),
        "signed": col(heads, "date of signing the contract", "date of signing", "signing"),
        "plan_end": col(heads, "date of completion plan", "completion plan"),
        "revenue": col(heads, "total project revenue", "revenue"),
    }
    out = []
    for i, row in enumerate(rows[h + 1:], start=h + 2):
        number = _txt(cell(row, c["num"]))
        name = _txt(cell(row, c["name"]))
        if not number and not name:
            continue
        raw_type = _txt(cell(row, c["type"]))
        raw_status = _txt(cell(row, c["status"]))
        dept, by_code = norm_type(raw_type, number)
        p = Project(
            number=number,
            name=name,
            dept=dept,
            status=norm_status(raw_status),
            stage=_txt(cell(row, c["stage"])),
            area=to_num(cell(row, c["area"])),
            revenue=to_num(cell(row, c["revenue"])),
            signed=to_date(cell(row, c["signed"])),
            plan_end=to_date(cell(row, c["plan_end"])),
            raw_status=raw_status,
            raw_type=raw_type,
            type_by_code=by_code,
        )
        for role in ("designer", "architect", "visualizer", "pm", "foreman"):
            who = _txt(cell(row, c[role]))
            if norm(who) not in _NOT_PEOPLE:
                p.people[role] = who
        label = number or name
        if by_code:
            issues.append(
                f"Общая таблица, строка {i}: у проекта {label} не указан тип — "
                f"считаю по коду как «{DEPT_RU[dept]}»"
            )
        elif dept == NOTYPE:
            issues.append(f"Общая таблица, строка {i}: у проекта {label} не указан тип")
        if p.status == UNKNOWN:
            what = f"непонятный статус «{raw_status}»" if raw_status else "не указан статус"
            issues.append(f"Общая таблица, строка {i}: у проекта {label} {what}")
        out.append(p)
    return out


def parse_dept_sheet(rows: list[list], dept: str, issues: list[str]) -> list[DeptRow]:
    title = DEPT_SHEET[dept]
    hit = find_header(rows, ["project number"])
    if not hit:
        if rows:
            issues.append(f"«{title}»: не нашёл строку заголовков (Project number)")
        return []
    h, heads = hit
    c_num = col(heads, "project number")
    c_name = col(heads, "project name")
    c_area = col(heads, "area, m2", "area m2", "area")
    c_type = col(heads, "project type")
    c_contract = col(heads, "contract total", "total project revenue")
    c_paid = col(heads, "paid", exact=True)
    if c_paid is None:
        c_paid = col(heads, "funds received")
    c_rem = col(heads, "remaining", exact=True)
    if c_rem is None:
        c_rem = col(heads, "balance to be received", "remaining")
    c_status = col(heads, "project status", "столбец 5")
    c_person = {
        DEV: col(heads, "responsible designer"),
        REAL: col(heads, "project manager"),
        KOMP: col(heads, "responsible ff&e designer", "ff&e designer"),
    }[dept]
    c_signed = col(heads, "date of signing", "signing the contract")
    c_plan = col(heads, "completion plan", "date of completion plan")
    pay_cols = [
        i for i, x in enumerate(heads)
        if re.fullmatch(r"payment( amount)? \d+", x)
    ]
    out: list[DeptRow] = []
    for i, row in enumerate(rows[h + 1:], start=h + 2):
        number = _txt(cell(row, c_num))
        if not number:
            continue
        contract = to_num(cell(row, c_contract))
        paid = to_num(cell(row, c_paid))
        if paid is None and pay_cols:
            parts = [x for x in (to_num(cell(row, j)) for j in pay_cols) if x is not None]
            paid = sum(parts) if parts else None
        rem = to_num(cell(row, c_rem))
        if rem is None and contract is not None and paid is not None:
            rem = contract - paid
        raw_status = _txt(cell(row, c_status))
        person = _txt(cell(row, c_person))
        r = DeptRow(
            dept=dept,
            number=number,
            name=_txt(cell(row, c_name)),
            status=norm_status(raw_status),
            person="" if norm(person) in _NOT_PEOPLE else person,
            area=to_num(cell(row, c_area)),
            contract=contract,
            paid=paid,
            remaining=rem,
            signed=to_date(cell(row, c_signed)),
            raw_type=_txt(cell(row, c_type)),
        )
        out.append(r)
        if r.status == UNKNOWN:
            what = f"непонятный статус «{raw_status}»" if raw_status else "не указан статус"
            issues.append(f"«{title}», строка {i}: у проекта {number} {what}")
        if r.status in (ACTIVE, PAUSED):
            if not r.person:
                issues.append(f"«{title}», строка {i}: у проекта {number} не указан ответственный")
            if dept == KOMP:
                if c_signed is not None and r.signed is None:
                    issues.append(f"«{title}», строка {i}: у проекта {number} нет даты подписания")
                if c_plan is not None and to_date(cell(row, c_plan)) is None:
                    issues.append(f"«{title}», строка {i}: у проекта {number} нет плановой даты завершения")
    return out


def parse_projects(data: dict) -> ProjectsData:
    issues: list[str] = []
    projects = parse_general(get_sheet(data, "Общая таблица"), issues)
    dept_rows = {d: parse_dept_sheet(get_sheet(data, DEPT_SHEET[d]), d, issues) for d in DEPTS}
    return ProjectsData(projects, dept_rows, issues)


# --- расчёты --------------------------------------------------------------------

def _sum(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def summary(pd: ProjectsData) -> dict:
    """Сводка по компании — по «Общей таблице»."""
    ps = pd.projects
    by_status = {s: sum(1 for p in ps if p.status == s) for s in (ACTIVE, PAUSED, DONE, REFUSED, NEW, UNKNOWN)}
    by_dept = {}
    for d in DEPTS + (NOTYPE,):
        dp = [p for p in ps if p.dept == d]
        by_dept[d] = {
            "total": len(dp),
            "active": sum(1 for p in dp if p.status == ACTIVE),
            "paused": sum(1 for p in dp if p.status == PAUSED),
        }
    return {"total": len(ps), "by_status": by_status, "by_dept": by_dept}


def dept_summary(pd: ProjectsData, d: str) -> dict:
    """Отдел — по его собственному листу. Деньги — по проектам «In progress»."""
    rows = pd.dept_rows.get(d, [])
    active = [r for r in rows if r.status == ACTIVE]
    return {
        "total": len(rows),
        "active": len(active),
        "paused": sum(1 for r in rows if r.status == PAUSED),
        "area_active": _sum(r.area for r in active),
        "contract": _sum(r.contract for r in active),
        "paid": _sum(r.paid for r in active),
        "remaining": _sum(r.remaining for r in active),
    }


def signed_in_month(pd: ProjectsData, year: int, month: int) -> list[Project]:
    return sorted(
        (p for p in pd.projects if p.signed and p.signed.year == year and p.signed.month == month),
        key=lambda p: p.signed,
    )


def people(pd: ProjectsData, d: str) -> list[str]:
    """Сотрудники отдела с проектами в работе или на паузе — по листу отдела."""
    return [w["name"] for w in workload(pd, d) if not w["total"]]


def person_projects(pd: ProjectsData, d: str, name: str) -> list[DeptRow]:
    """Проекты человека в работе и на паузе — по листу отдела."""
    n = norm(name)
    rows = [r for r in pd.dept_rows.get(d, []) if r.status in (ACTIVE, PAUSED) and norm(r.person) == n]
    return sorted(rows, key=lambda r: (r.status != ACTIVE, r.number))


def workload(pd: ProjectsData, d: str) -> list[dict]:
    """Загрузка по листу отдела: на человека — проекты в работе / на паузе,
    м² и остаток оплат по проектам в работе. Последняя строка — «Итого»."""
    by: dict[str, dict] = {}
    for r in pd.dept_rows.get(d, []):
        if r.status not in (ACTIVE, PAUSED) or not r.person:
            continue
        w = by.setdefault(norm(r.person), {
            "name": r.person, "total": False, "projects": 0, "paused": 0,
            "area": None, "remaining": None,
        })
        if r.status == PAUSED:
            w["paused"] += 1
            continue
        w["projects"] += 1
        if r.area is not None:
            w["area"] = (w["area"] or 0) + r.area
        if r.remaining is not None:
            w["remaining"] = (w["remaining"] or 0) + r.remaining
    rows = sorted(by.values(), key=lambda w: (-w["projects"], w["name"]))
    if rows:
        rows.append({
            "name": "Итого", "total": True,
            "projects": sum(w["projects"] for w in rows),
            "paused": sum(w["paused"] for w in rows),
            "area": _sum(w["area"] for w in rows),
            "remaining": _sum(w["remaining"] for w in rows),
        })
    return rows


def query_projects(
    pd: ProjectsData,
    department: str | None = None,
    status: str | None = None,
    person: str | None = None,
    signed_from: dt.date | None = None,
    signed_to: dt.date | None = None,
    limit: int = 60,
) -> dict:
    """Для «💬 Спросить»: проекты с фильтрами + итоги (компактный JSON).

    С отделом или человеком — по листам отделов (там деньги и ответственные),
    без них — по «Общей таблице».
    """
    if department or person:
        depts = [department] if department in DEPTS else list(DEPTS)
        rows = [r for d in depts for r in pd.dept_rows.get(d, [])]
        if status:
            rows = [r for r in rows if r.status == status]
        if person:
            n = norm(person)
            rows = [r for r in rows if n in norm(r.person)]
        if signed_from:
            rows = [r for r in rows if r.signed and r.signed >= signed_from]
        if signed_to:
            rows = [r for r in rows if r.signed and r.signed <= signed_to]
        items = [
            {
                "number": r.number, "name": strip_number(r.name, r.number), "department": r.dept,
                "status": r.status, "responsible": r.person, "area_m2": r.area,
                "contract_dh": r.contract, "paid_dh": r.paid, "remaining_dh": r.remaining,
                "signed": r.signed.isoformat() if r.signed else None,
            }
            for r in rows
        ]
        totals = {
            "total_area_m2": _sum(r.area for r in rows),
            "total_contract_dh": _sum(r.contract for r in rows),
            "total_paid_dh": _sum(r.paid for r in rows),
            "total_remaining_dh": _sum(r.remaining for r in rows),
        }
        source = "листы отделов"
    else:
        ps = pd.projects
        if status:
            ps = [p for p in ps if p.status == status]
        if signed_from:
            ps = [p for p in ps if p.signed and p.signed >= signed_from]
        if signed_to:
            ps = [p for p in ps if p.signed and p.signed <= signed_to]
        items = [
            {
                "number": p.number, "name": strip_number(p.name, p.number), "department": p.dept,
                "status": p.status, "stage": p.stage, "area_m2": p.area,
                "revenue_dh": p.revenue, "signed": p.signed.isoformat() if p.signed else None,
                "responsible": p.people,
            }
            for p in ps
        ]
        totals = {
            "total_area_m2": _sum(p.area for p in ps),
            "total_revenue_dh": _sum(p.revenue for p in ps),
        }
        source = "Общая таблица"
    return {
        "source": source,
        "count": len(items),
        **totals,
        "projects": items[:limit],
        "truncated": len(items) > limit,
    }
