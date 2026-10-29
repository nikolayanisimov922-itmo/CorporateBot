"""«👥 HR»: разбор таблицы найма hiring_pipeline (чистые функции).

Лист = месяц (september, october…). По горизонтали — блоки недель (в первой строке
блока диапазон дат «12.10 - 16.10.2026»), внутри по вертикали — блоки ролей:
название роли, priority/comments, строка «sources | HH | LinkedIn | … | Total |
Conversion», затем строки этапов (responses, HR screening, …).

Парсим по ячейкам-якорям, а не по адресам: роли, источники и этапы различаются
от блока к блоку. Total и Conversion пересчитываем сами.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.management_data import MONTHS_EN, cell, norm, to_num

_RANGE = re.compile(r"\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\s*[-–—]\s*\d{1,2}\.\d{1,2}(?:\.\d{2,4})?")

# Этапы воронки по порядку: (код, подпись RU, варианты названий в таблице).
STAGES = [
    ("responses", "Отклики", ("responses", "response", "отклики")),
    ("screening", "Скрининг", ("hr screening", "screening", "скрининг")),
    ("interview", "Интервью", ("1st step interview", "first step interview", "interview", "интервью")),
    ("test", "Тестовое", ("test assignment", "test", "тестовое")),
    ("tech", "Тех. интервью", ("tech interview", "technical interview", "тех")),
    ("offer", "Оффер", ("offer", "оффер")),
    ("joining", "Выход", ("joining", "joined", "выход")),
]
STAGE_RU = {code: ru for code, ru, _ in STAGES}

# Синонимы ролей (одна вакансия называется по-разному в разные недели).
# TODO уточнить у HR полный список.
ROLE_SYNONYMS = {
    "sales manager usa": "Sales USA",
    "sales usa": "Sales USA",
    "civil engineer dubai": "Civil Engineer",
    "civil engineer": "Civil Engineer",
    "cmo remote": "CMO",
    "cmo": "CMO",
}
_NOT_ROLE = ("priority", "comments", "comment", "sources")


def canon_role(name: str) -> str:
    return ROLE_SYNONYMS.get(norm(name), " ".join(str(name).split()))


def _stage_code(label: str) -> str | None:
    n = norm(label)
    if not n:
        return None
    # Сначала «tech interview», чтобы не принять его за обычное «interview».
    for code, _, names in sorted(STAGES, key=lambda s: -max(len(x) for x in s[2])):
        for x in names:
            if n == x or n.startswith(x):
                return code
    return None


@dataclass
class RoleWeek:
    role: str  # каноническое имя
    raw_role: str
    week: str
    sources: list[str]
    counts: dict = field(default_factory=dict)  # этап → {источник: число}

    def total(self, stage: str) -> float:
        return sum(v for v in self.counts.get(stage, {}).values() if v is not None)


def parse_hiring_sheet(rows: list[list]) -> list[RoleWeek]:
    if not rows:
        return []
    top = rows[0]
    starts = [i for i, v in enumerate(top) if _RANGE.search(str(v or ""))]
    out: list[RoleWeek] = []
    for bi, c0 in enumerate(starts):
        c1 = starts[bi + 1] if bi + 1 < len(starts) else max(len(r) for r in rows)
        week = _RANGE.search(str(top[c0])).group(0).replace(" ", "")
        for r, row in enumerate(rows):
            if norm(cell(row, c0)) != "sources":
                continue
            # Источники — из этой же строки, до Total/Conversion.
            src_cols = {}
            for j in range(c0 + 1, c1):
                name = str(cell(row, j) or "").strip()
                if not name:
                    continue
                if norm(name) in ("total", "conversion", "итого", "конверсия"):
                    continue
                src_cols[j] = name
            # Название роли — ближайшая сверху ячейка, которая не priority/comments.
            raw_role = ""
            for k in range(r - 1, max(-1, r - 5), -1):
                v = str(cell(rows[k], c0) or "").strip()
                if v and not norm(v).startswith(_NOT_ROLE) and not _RANGE.search(v):
                    raw_role = v
                    break
            if not raw_role:
                continue
            rw = RoleWeek(canon_role(raw_role), raw_role, week, list(src_cols.values()))
            for k in range(r + 1, min(len(rows), r + 10)):
                code = _stage_code(cell(rows[k], c0) or "")
                if code is None:
                    if norm(cell(rows[k], c0)) in ("", "sources"):
                        break
                    continue
                rw.counts[code] = {name: to_num(cell(rows[k], j)) for j, name in src_cols.items()}
            out.append(rw)
    return out


def parse_hiring(data: dict) -> dict[int, list[RoleWeek]]:
    """{номер месяца: блоки} по листам с английскими названиями месяцев."""
    out = {}
    for title, rows in data.items():
        n = norm(title)
        if n in MONTHS_EN:
            out[MONTHS_EN.index(n) + 1] = parse_hiring_sheet(rows)
    return out


def roles(blocks: list[RoleWeek]) -> list[str]:
    seen = []
    for b in blocks:
        if b.role not in seen:
            seen.append(b.role)
    return seen


def funnel(blocks: list[RoleWeek], role: str, week: str | None = None) -> dict:
    """Сумма по этапам (и источникам откликов) для роли: за неделю или за весь лист."""
    sel = [b for b in blocks if b.role == role and (week is None or b.week == week)]
    stages = {code: sum(b.total(code) for b in sel) for code, _, _ in STAGES}
    present = {code for b in sel for code in b.counts}
    sources: dict[str, float] = {}
    for b in sel:
        for s, v in b.counts.get("responses", {}).items():
            if v:
                sources[s] = sources.get(s, 0) + v
    return {"stages": stages, "present": present, "sources": sources, "weeks": len(sel)}


def last_week(blocks: list[RoleWeek], role: str) -> str | None:
    """Последняя неделя, где у роли есть хоть один отклик."""
    weeks = [b.week for b in blocks if b.role == role and b.total("responses") > 0]
    return weeks[-1] if weeks else None


def hiring_query(blocks: list[RoleWeek], role: str | None, week: str | None) -> dict:
    """Для «💬 Спросить»."""
    names = [role] if role else roles(blocks)
    out = {}
    for r in names:
        match = next((x for x in roles(blocks) if norm(x) == norm(r)), None)
        if match is None:
            continue
        out[match] = funnel(blocks, match, week)
        out[match]["present"] = sorted(out[match]["present"])
    return {"weeks": sorted({b.week for b in blocks}), "roles": out}
