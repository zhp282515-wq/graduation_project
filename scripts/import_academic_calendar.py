"""校历导入：读 config/calendar/*.yaml，幂等写入 academic_term / academic_calendar。

每学期更新流程：
  1. 复制上一学期的 yaml，改名（如 2027_spring.yaml）
  2. 改 term_start / term_end，照校历「说明」栏填 events
  3. uv run python scripts/import_calendar.py

同一学期重复导入会先清空该学期的事件再写入，因此删掉的事件会同步消失。
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

_REPO_ROOT = Path(__file__).resolve().parent.parent
CALENDAR_DIR = _REPO_ROOT / "config" / "calendar"
_SCHEMA_SQL = _REPO_ROOT / "scripts" / "academic_calendar_schema.sql"

# 已知事件类型。填错会直接报错，避免错别字静默变成新类别；要加类型在这里补一行。
EVENT_TYPES = {
    "staff_report", "registration", "class_start", "enrollment",
    "holiday", "makeup_class", "midterm_exam", "final_exam",
    "exam_makeup", "exam_review", "sports_meet", "vacation_start", "other",
}
TERMS = {"spring", "fall"}
AUDIENCES = {"all", "undergrad", "graduate", "staff"}
# 供工具层生成 schema 用；顺序决定 enum 呈现顺序
EventTypeLiteral = Literal[
    "staff_report", "registration", "class_start", "enrollment",
    "holiday", "makeup_class", "midterm_exam", "final_exam",
    "exam_makeup", "exam_review", "sports_meet", "vacation_start", "other",
]


def _as_date(value, field: str, path: Path) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ValueError(f"{path.name}: {field} 需为 YYYY-MM-DD，收到 {value!r}")


def load_term(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    for key in ("academic_year", "term", "term_start", "term_end"):
        if not raw.get(key):
            raise ValueError(f"{path.name}: 缺少必填字段 {key}")
    if raw["term"] not in TERMS:
        raise ValueError(f"{path.name}: term 只能是 {sorted(TERMS)}，收到 {raw['term']!r}")

    start = _as_date(raw["term_start"], "term_start", path)
    end = _as_date(raw["term_end"], "term_end", path)
    if start.weekday() != 0:
        raise ValueError(
            f"{path.name}: term_start 必须是周一（第 1 周周一 = 正式上课日），"
            f"{start} 是周{start.weekday() + 1}"
        )
    if end < start:
        raise ValueError(f"{path.name}: term_end ({end}) 早于 term_start ({start})")

    events = []
    for i, ev in enumerate(raw.get("events") or [], start=1):
        where = f"{path.name} events[{i}]"
        etype = ev.get("type")
        if etype not in EVENT_TYPES:
            raise ValueError(
                f"{where}: 未知 type {etype!r}，可用：{', '.join(sorted(EVENT_TYPES))}"
            )
        if not ev.get("name") or not ev.get("start"):
            raise ValueError(f"{where}: name 和 start 必填")
        e_start = _as_date(ev["start"], "start", path)
        e_end = _as_date(ev.get("end", ev["start"]), "end", path)
        if e_end < e_start:
            raise ValueError(f"{where}: end 早于 start")

        weekday = ev.get("makeup_weekday")
        if weekday is not None:
            if etype != "makeup_class":
                raise ValueError(f"{where}: makeup_weekday 只对 makeup_class 有意义")
            if not isinstance(weekday, int) or not 1 <= weekday <= 7:
                raise ValueError(f"{where}: makeup_weekday 应为 1~7（1=周一）")

        audience = ev.get("audience", "all")
        if audience not in AUDIENCES:
            raise ValueError(f"{where}: audience 只能是 {sorted(AUDIENCES)}")

        events.append({
            "event_type": etype, "name": ev["name"],
            "start_date": e_start, "end_date": e_end,
            "affects_weekday": weekday, "audience": audience,
            "is_tentative": bool(ev.get("tentative", False)),
            "note": ev.get("note"),
        })

    for i, a in enumerate(raw.get("anchors") or [], start=1):
        if "date" not in a or "week" not in a:
            raise ValueError(f"{path.name} anchors[{i}]: 需要 date 和 week")
        d = _as_date(a["date"], "date", path)
        actual = (d - start).days // 7 + 1
        if actual != a["week"]:
            raise ValueError(
                f"{path.name} anchors[{i}]: {d} 按 term_start={start} 算出第 {actual} 周，"
                f"与锚点声明的第 {a['week']} 周不符——term_start 很可能填错了"
            )

    return {
        "academic_year": raw["academic_year"], "term": raw["term"],
        "term_start": start, "term_end": end,
        "source_file": path.name, "events": events,
    }


def import_term(conn, spec: dict) -> tuple[int, int]:
    term_id = conn.execute(
        """
        INSERT INTO academic_term (academic_year, term, term_start, term_end)
        VALUES (%(academic_year)s, %(term)s, %(term_start)s, %(term_end)s)
        ON CONFLICT (academic_year, term) DO UPDATE
            SET term_start = EXCLUDED.term_start,
                term_end   = EXCLUDED.term_end
        RETURNING id
        """,
        spec,
    ).fetchone()[0]

    # 整体覆盖：先清空该学期事件，再写入 YAML 里的全量，删除的事件才会真正消失
    deleted = conn.execute(
        "DELETE FROM academic_calendar WHERE term_id = %s", (term_id,)
    ).rowcount

    for ev in spec["events"]:
        conn.execute(
            """
            INSERT INTO academic_calendar
                (term_id, event_type, name, start_date, end_date, affects_weekday,
                 audience, is_tentative, note, source_file)
            VALUES
                (%(term_id)s, %(event_type)s, %(name)s, %(start_date)s, %(end_date)s,
                 %(affects_weekday)s, %(audience)s, %(is_tentative)s, %(note)s,
                 %(source_file)s)
            """,
            {**ev, "term_id": term_id, "source_file": spec["source_file"]},
        )
    return deleted, len(spec["events"])


def main() -> None:
    parser = argparse.ArgumentParser(description="导入校历 YAML 到 PostgreSQL")
    parser.add_argument("--file", help="只导入指定文件，缺省导入 config/calendar/*.yaml 全部")
    args = parser.parse_args()

    paths = [Path(args.file)] if args.file else sorted(CALENDAR_DIR.glob("*.yaml"))
    if not paths:
        raise SystemExit(f"没有找到校历文件：{CALENDAR_DIR}")

    specs = [load_term(p) for p in paths]

    dsn = os.getenv("LANGGRAPH_POSTGRES_URI")
    if not dsn:
        raise RuntimeError("缺少 LANGGRAPH_POSTGRES_URI 配置")

    with psycopg.connect(dsn) as conn:
        conn.execute(_SCHEMA_SQL.read_text(encoding="utf-8"))
        for spec in specs:
            deleted, written = import_term(conn, spec)
            print(
                f"[ok] {spec['academic_year']} {spec['term']}"
                f"（{spec['source_file']}）：清理 {deleted} 条，写入 {written} 条"
            )
        conn.commit()


if __name__ == "__main__":
    main()