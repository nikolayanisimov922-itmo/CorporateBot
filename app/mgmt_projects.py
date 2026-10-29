"""«📁 Проекты»: разбор мастер-таблицы и расчёты (чистые функции, без сети).

Источник сводки — лист «Общая таблица»; деньги (контракт, оплачено, остаток) —
листы отделов; загрузка по людям — готовые листы «Загрузка …» (их цифры
«официальные»), а собственный расчёт по «Общей таблице» — для сверки в /mgmt_check.
Заголовки ищем по тексту, а не по номерам строк/колонок — таблицы правят руками.
"""
from __future__ import annotations

import datetime as dt
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
# «Не люди» в колонках ответственных.
_NOT_PEOPLE = {"without a project", "без проекта", ""}

DEPT_SHEET = {DEV: "Отдел разработки", REAL: "Отдел реализации", KOMP: "Отдел комплектации"}
LOAD_SHEET = {
    DEV: "Загрузка (отдел разработки)",
    REAL: "Загрузка отдела реализации",
    KOMP: "Загрузка отдела комплектации",
}


def norm_status(v) -> str:
    return _STATUS.get(norm(v), UNKNOWN if not norm(v) else UNKNOWN)


def norm_type(v) -> str:
    return _TYPE.get(norm(v), NOTYPE)


@dataclass
class Project:
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
    # Деньги с листа отдела (если нашлись):
    contract: float | None = None
    paid: float | None = None
    remaining: float | None = None
    raw_status: str = ""
    raw_type: str = ""


@dataclass
class ProjectsData:
    projects: list[Project]
    workload: dict  # отдел → [{"name", "projects", "area", ...}], с листов «Загрузка …»
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
        p = Project(
            number=number,
            name=name,
            dept=norm_type(raw_type),
            status=norm_status(raw_status),
            stage=_txt(cell(row, c["stage"])),
            area=to_num(cell(row, c["area"])),
            revenue=to_num(cell(row, c["revenue"])),
            signed=to_date(cell(row, c["signed"])),
            plan_end=to_date(cell(row, c["plan_end"])),
            raw_status=raw_status,
            raw_type=raw_type,
        )
        for role in ("designer", "architect", "visualizer", "pm", "foreman"):
            who = _txt(cell(row, c[role]))
            if norm(who) not in _NOT_PEOPLE:
                p.people[role] = who
        if p.dept == NOTYPE:
            issues.append(f"Общая таблица, строка {i}: у проекта {number or name} не указан тип")
        if p.status == UNKNOWN:
            what = f"непонятный статус «{raw_status}»" if raw_status else "не указан статус"
            issues.append(f"Общая таблица, строка {i}: у проекта {number or name} {what}")
        out.append(p)
    return out


def _dept_money(rows: list[list], dept: str, issues: list[str]) -> dict[str, dict]:
    """Деньги и ответственные с листа отдела: {номер проекта: {...}}."""
    title = DEPT_SHEET[dept]
    hit = find_header(rows, ["project number"])
    if not hit:
        if rows:
            issues.append(f"«{title}»: не нашёл строку заголовков (Project number)")
        return {}
    h, heads = hit
    c_num = col(heads, "project number")
    c_contract = col(heads, "contract total", "total project revenue")
    c_paid = col(heads, "paid", "funds received", exact=True) or col(heads, "funds received")
    c_rem = col(heads, "remaining", "balance to be received", exact=True) or col(
        heads, "balance to be received", "remaining"
    )
    c_status = col(heads, "project status", "столбец 5")
    c_person = col(heads, "responsible ff&e designer", "project manager", "responsible designer")
    c_signed = col(heads, "date of signing", "signing the contract")
    c_plan = col(heads, "completion plan", "date of completion plan")
    pay_cols = [i for i, x in enumerate(heads) if x.startswith("payment ") and x[8:].strip().isdigit()]
    out: dict[str, dict] = {}
    for i, row in enumerate(rows[h + 1:], start=h + 2):
        number = _txt(cell(row, c_num))
        if not number:
            continue
        contract = to_num(cell(row, c_contract))
        paid = to_num(cell(row, c_paid))
        if paid is None and pay_cols:
            parts = [to_num(cell(row, j)) for j in pay_cols]
            parts = [x for x in parts if x is not None]
            paid = sum(parts) if parts else None
        rem = to_num(cell(row, c_rem))
        if rem is None and contract is not None and paid is not None:
            rem = contract - paid
        status = norm_status(cell(row, c_status)) if c_status is not None else UNKNOWN
        out[number] = {
            "contract": contract, "paid": paid, "remaining": rem,
            "person": _txt(cell(row, c_person)), "status": status,
        }
        if dept == KOMP and status in (ACTIVE, PAUSED):
            if c_signed is not None and to_date(cell(row, c_signed)) is None:
                issues.append(f"«{title}», строка {i}: у проекта {number} нет даты подписания")
            if c_plan is not None and to_date(cell(row, c_plan)) is None:
                issues.append(f"«{title}», строка {i}: у проекта {number} нет плановой даты завершения")
    return out


def parse_workload(rows: list[list], dept: str) -> list[dict]:
    """Готовая загрузка с листа «Загрузка …»: строки сотрудников + «Итого»."""
    hit = find_header(rows, ["projects now"])
    if not hit:
        return []
    h, heads = hit
    c_name = 0
    for i, x in enumerate(heads):
        if x in ("designer", "project manager", "designer / project manager"):
            c_name = i
            break
    c_now = col(heads, "projects now")
    c_area = col(heads, "current area")
    extra = {
        "remaining": col(heads, "remaining payment now"),
        "paused": col(heads, "projects on pause"),
        "equipment": col(heads, "equipment"),
        "commission": col(heads, "commission"),
        "supervision": col(heads, "author's supervision", "authors supervision"),
    }
    out = []
    for row in rows[h + 1:]:
        name = _txt(cell(row, c_name))
        if not name:
            if out:
                break  # ниже листа — другие таблицы (помесячная динамика и т.п.)
            continue
        if norm(name) in _NOT_PEOPLE:
            continue
        item = {
            "name": name,
            "total": norm(name) in ("total", "итого", "всего"),
            "projects": to_num(cell(row, c_now)),
            "area": to_num(cell(row, c_area)),
        }
        for k, j in extra.items():
            if j is not None:
                item[k] = to_num(cell(row, j))
        out.append(item)
        if item["total"]:
            break
    return out


def parse_projects(data: dict) -> ProjectsData:
    issues: list[str] = []
    projects = parse_general(get_sheet(data, "Общая таблица"), issues)
    by_num = {p.number: p for p in projects if p.number}
    for dept in DEPTS:
        money = _dept_money(get_sheet(data, DEPT_SHEET[dept]), dept, issues)
        for number, m in money.items():
            p = by_num.get(number)
            if p is None:
                continue
            p.contract, p.paid, p.remaining = m["contract"], m["paid"], m["remaining"]
            if m["person"] and norm(m["person"]) not in _NOT_PEOPLE:
                p.people.setdefault("dept_person", m["person"])
    workload = {d: parse_workload(get_sheet(data, LOAD_SHEET[d]), d) for d in DEPTS}
    issues += _workload_check(projects, workload)
    return ProjectsData(projects, workload, issues)


# --- расчёты --------------------------------------------------------------------

def person_of(p: Project) -> str:
    """Главный ответственный проекта в его отделе."""
    if p.dept == DEV:
        return p.people.get("designer") or p.people.get("dept_person", "")
    if p.dept == REAL:
        return p.people.get("pm") or p.people.get("dept_person", "")
    if p.dept == KOMP:
        return p.people.get("dept_person") or p.people.get("pm", "")
    return ""


def summary(pd: ProjectsData) -> dict:
    ps = pd.projects
    by_status = {s: sum(1 for p in ps if p.status == s) for s in (ACTIVE, PAUSED, DONE, REFUSED, NEW, UNKNOWN)}
    by_dept = {}
    for d in DEPTS + (NOTYPE,):
        dp = [p for p in ps if p.dept == d]
        live = [p for p in dp if p.status in (ACTIVE, PAUSED)]
        by_dept[d] = {
            "total": len(dp),
            "active": sum(1 for p in dp if p.status == ACTIVE),
            "paused": sum(1 for p in dp if p.status == PAUSED),
            "area_active": sum(p.area or 0 for p in dp if p.status == ACTIVE),
            "contract": _sum(p.contract if p.contract is not None else p.revenue for p in live),
            "paid": _sum(p.paid for p in live),
            "remaining": _sum(p.remaining for p in live),
        }
    return {"total": len(ps), "by_status": by_status, "by_dept": by_dept}


def _sum(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def signed_in_month(pd: ProjectsData, year: int, month: int) -> list[Project]:
    return sorted(
        (p for p in pd.projects if p.signed and p.signed.year == year and p.signed.month == month),
        key=lambda p: p.signed,
    )


def own_workload(pd: ProjectsData, dept: str) -> dict[str, dict]:
    """Загрузка по «Общей таблице»: активные проекты и м² на человека."""
    out: dict[str, dict] = {}
    for p in pd.projects:
        if p.dept != dept or p.status != ACTIVE:
            continue
        who = person_of(p)
        if not who:
            continue
        w = out.setdefault(who, {"projects": 0, "area": 0.0})
        w["projects"] += 1
        w["area"] += p.area or 0
    return out


def _workload_check(projects: list[Project], workload: dict) -> list[str]:
    pd = ProjectsData(projects, workload, [])
    out = []
    for d in DEPTS:
        mine = {norm(k): v for k, v in own_workload(pd, d).items()}
        for row in workload.get(d, []):
            if row["total"] or row.get("projects") is None:
                continue
            own = mine.get(norm(row["name"]))
            if own and int(own["projects"]) != int(row["projects"]):
                out.append(
                    f"Загрузка «{DEPT_RU[d]}», {row['name']}: на листе «Загрузка» "
                    f"{int(row['projects'])} проектов, по «Общей таблице» — {own['projects']}"
                )
    return out


def person_projects(pd: ProjectsData, dept: str, name: str) -> list[Project]:
    n = norm(name)
    return [
        p for p in pd.projects
        if p.dept == dept and p.status in (ACTIVE, PAUSED) and norm(person_of(p)) == n
    ]


def query_projects(
    pd: ProjectsData,
    department: str | None = None,
    status: str | None = None,
    person: str | None = None,
    signed_from: dt.date | None = None,
    signed_to: dt.date | None = None,
    limit: int = 60,
) -> dict:
    """Для «💬 Спросить»: отфильтрованные проекты + агрегаты (компактный JSON)."""
    ps = pd.projects
    if department:
        ps = [p for p in ps if p.dept == department]
    if status:
        ps = [p for p in ps if p.status == status]
    if person:
        n = norm(person)
        ps = [p for p in ps if any(n in norm(v) for v in p.people.values())]
    if signed_from:
        ps = [p for p in ps if p.signed and p.signed >= signed_from]
    if signed_to:
        ps = [p for p in ps if p.signed and p.signed <= signed_to]
    items = [
        {
            "number": p.number, "name": p.name, "department": p.dept, "status": p.status,
            "stage": p.stage, "area_m2": p.area,
            "contract_dh": p.contract if p.contract is not None else p.revenue,
            "paid_dh": p.paid, "remaining_dh": p.remaining,
            "signed": p.signed.isoformat() if p.signed else None,
            "responsible": p.people,
        }
        for p in ps
    ]
    return {
        "count": len(items),
        "total_area_m2": _sum(p.area for p in ps),
        "total_contract_dh": _sum((p.contract if p.contract is not None else p.revenue) for p in ps),
        "total_paid_dh": _sum(p.paid for p in ps),
        "total_remaining_dh": _sum(p.remaining for p in ps),
        "projects": items[:limit],
        "truncated": len(items) > limit,
    }
