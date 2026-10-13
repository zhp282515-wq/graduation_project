"""校历查询工具：教学周、节假日、补课、考试安排等结构化查询。

数据在 PostgreSQL 的 academic_term / academic_calendar 两张表里，
不走 Milvus —— 日期需要精确算术，相似度检索没有意义。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any
from typing_extensions import get_args

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from agent.tools.base import BaseTool, ToolError
from scripts.import_academic_calendar import EventTypeLiteral
from utils.logger_tool import logger

load_dotenv(override=True)

_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
_TERM_CN = {"spring": "春季", "fall": "秋季"}
_NO_CLASS_TYPES = {"holiday", "vacation_start"}
_AUDIENCES = {"all", "undergrad", "graduate", "staff"}


def _weekday_cn(d: date) -> str:
    return f"周{_WEEKDAY_CN[d.weekday()]}"


def _parse_date(raw: Any, field: str) -> date | None:
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise ToolError(f"参数 {field} 应为 YYYY-MM-DD 字符串")
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ToolError(f"参数 {field} 需为 YYYY-MM-DD 格式，收到：{raw!r}")


class AcademicCalendarTool(BaseTool):
    @property
    def name(self) -> str:
        return "academic_calendar"

    @property
    def description(self) -> str:
        return """
        校历查询工具。用于回答与教学周、放假、补课、考试时间相关问题。
        能力：
        - day_info：查某一天的教学周次、是否放假、是否补课、该上哪天的课
        - week_number：只查某日期是第几教学周
        "- list_events：按学期列出事件（放假、考试、校运会等）。问"几号放假/开学/考试"用 event_types 过滤，"
"不要拉全学期再筛。寒假暑假的起点是 vacation_start 类型。\n"
        - list_terms：列出已录入的学期
        使用原则：
        - 涉及"今天是第几周""哪天放假""什么时候考试""这周三上不上课"这类问题，必须用本工具，
          不要依赖知识库检索或模型自身推算——日期计算必须精确。
        - 默认日期为今天，需要换算时显式传 date。
        - 补课日（如"补周五的课"）工具会明确指出，回答时照抄工具的判定，不要自行推断。
        - 标记为暂定（is_tentative）的事件要提醒用户可能调整。
        """

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["day_info", "week_number", "list_events", "list_terms"],
                    "description": "查询类型",
                },
                "date": {
                    "type": "string",
                    "description": "YYYY-MM-DD，缺省为今天。day_info / week_number 用",
                },
                "academic_year": {
                    "type": "string",
                    "description": "如 '2026-2027'。list_events 用，缺省为当前学期",
                },
                "term": {
                    "type": "string",
                    "enum": ["spring", "fall"],
                    "description": "list_events 用，缺省为当前学期",
                },
                "event_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(get_args(EventTypeLiteral))},
                    "description": "可选，过滤事件类型。all = 全部事件；"
                                   "vacation_start = 假期开始（寒暑假）；holiday = 法定节假日；"
                                   "makeup_class = 补课；上课相关：class_start/registration/enrollment；"
                                   "考试相关：midterm_exam/final_exam/exam_review/exam_makeup；"
                                   "其他：sports_meet/staff_report/other。"
                                   "问假期起止必须先按 vacation_start 过滤。",
                },
                "audience": {
                    "type": "string",
                    "enum": ["all", "undergrad", "graduate", "staff"],
                    "description": "身份视角，缺省 undergrad。区分本/研安排时用",
                },
            },
            "required": ["query_type"],
        }

    # ── 数据库 ────────────────────────────────────────────
    @staticmethod
    def _connect() -> psycopg.Connection:
        dsn = os.getenv("LANGGRAPH_POSTGRES_URI")
        if not dsn:
            raise ToolError("缺少 LANGGRAPH_POSTGRES_URI 配置，无法查询校历")
        return psycopg.connect(dsn, row_factory=dict_row)

    @staticmethod
    def _events_on(conn, d: date, audience: str) -> list[dict[str, Any]]:
        return conn.execute(
            """
            SELECT c.*, t.academic_year, t.term
            FROM academic_calendar c
            JOIN academic_term t ON t.id = c.term_id
            WHERE c.start_date <= %s AND c.end_date >= %s
              AND c.audience IN ('all', %s)
            ORDER BY c.start_date, c.id
            """,
            (d, d, audience),
        ).fetchall()

    @staticmethod
    def _term_of(conn, d: date) -> dict[str, Any] | None:
        return conn.execute(
            """
            SELECT * FROM academic_term
            WHERE term_start <= %s AND term_end >= %s
            ORDER BY term_start DESC LIMIT 1
            """,
            (d, d),
        ).fetchone()

    @staticmethod
    def _current_term(conn, d: date) -> dict[str, Any]:
        term = AcademicCalendarTool._term_of(conn, d)
        if term is None:
            raise ToolError(f"{d.isoformat()} 不在任何已录入的教学周内，无法确定当前学期")
        return term

    @staticmethod
    def _week_no(term: dict[str, Any], d: date) -> int:
        return (d - term["term_start"]).days // 7 + 1

    # ── 入口 ──────────────────────────────────────────────
    def run(self, **kwargs) -> str:
        query_type = kwargs.get("query_type", "")
        audience = kwargs.get("audience") or "undergrad"
        if audience not in _AUDIENCES:
            raise ToolError(f"audience 只能是 {sorted(_AUDIENCES)}，收到：{audience!r}")

        handlers = {
            "day_info": self._day_info,
            "week_number": self._week_number,
            "list_events": self._list_events,
            "list_terms": self._list_terms,
        }
        handler = handlers.get(query_type)
        if handler is None:
            raise ToolError(
                f"不支持的 query_type：{query_type!r}，可用：{', '.join(handlers)}"
            )

        with self._connect() as conn:
            return handler(conn, kwargs, audience)

    # ── 各类型实现 ────────────────────────────────────────
    def _day_info(self, conn, kwargs, audience: str) -> str:
        d = _parse_date(kwargs.get("date"), "date") or date.today()
        term = self._term_of(conn, d)
        events = self._events_on(conn, d, audience)

        lines = [f"日期：{d.isoformat()}（{_weekday_cn(d)}）"]

        if term is not None:
            lines.append(
                f"学期：{term['academic_year']} {_TERM_CN[term['term']]}学期"
                f" · 第 {self._week_no(term, d)} 教学周"
            )
        else:
            lines.append("学期：不在教学周内（假期或学期之间）")

        makeup = next(
            (e for e in events if e["event_type"] == "makeup_class" and e["affects_weekday"]),
            None,
        )
        no_class = [e for e in events if e["event_type"] in _NO_CLASS_TYPES]

        if makeup is not None:
            wd = _WEEKDAY_CN[makeup["affects_weekday"] - 1]
            lines.append(f"上课安排：按周{wd}的课表上课（{makeup['name']}）")
        elif no_class:
            lines.append(f"上课安排：停课（{no_class[0]['name']}）")
        elif term is not None:
            lines.append(f"上课安排：正常上课，按{_weekday_cn(d)}的课表")
        else:
            lines.append("上课安排：无课")

        if events:
            lines.append("当日事件：")
            lines.extend(f"  - {self._fmt_event(e)}" for e in events)
        else:
            lines.append("当日事件：无")

        return "\n".join(lines)

    def _week_number(self, conn, kwargs, audience: str) -> str:
        d = _parse_date(kwargs.get("date"), "date") or date.today()
        term = self._term_of(conn, d)
        if term is None:
            return f"{d.isoformat()}（{_weekday_cn(d)}）不在教学周内"
        return (
            f"{d.isoformat()}（{_weekday_cn(d)}）是 "
            f"{term['academic_year']} {_TERM_CN[term['term']]}学期 第 {self._week_no(term, d)} 教学周"
        )

    def _list_events(self, conn, kwargs, audience: str) -> str:
        year = kwargs.get("academic_year")
        term_name = kwargs.get("term")

        if not year or not term_name:
            current = self._current_term(conn, _parse_date(kwargs.get("date"), "date") or date.today())
            year = year or current["academic_year"]
            term_name = term_name or current["term"]
        if term_name not in _TERM_CN:
            raise ToolError(f"term 只能是 spring 或 fall，收到：{term_name!r}")

        sql = """
            SELECT c.* FROM academic_calendar c
            JOIN academic_term t ON t.id = c.term_id
            WHERE t.academic_year = %s AND t.term = %s
              AND c.audience IN ('all', %s)
        """
        params: list[Any] = [year, term_name, audience]

        event_types = kwargs.get("event_types")
        if event_types:
            if not isinstance(event_types, list):
                raise ToolError("event_types 应为数组")
            sql += " AND c.event_type = ANY(%s)"
            params.append(list(event_types))

        rows = conn.execute(sql + " ORDER BY c.start_date, c.id", params).fetchall()
        header = f"{year} {_TERM_CN[term_name]}学期 校历事件（{len(rows)} 条）："
        if not rows:
            return header + "\n  （无）"
        return header + "\n" + "\n".join(f"  - {self._fmt_event(e)}" for e in rows)

    def _list_terms(self, conn, kwargs, audience: str) -> str:
        rows = conn.execute(
            "SELECT * FROM academic_term ORDER BY term_start DESC"
        ).fetchall()
        if not rows:
            return "尚未录入任何学期"
        return "已录入学期：\n" + "\n".join(
            f"  - {r['academic_year']} {_TERM_CN[r['term']]}学期"
            f"：{r['term_start']} ~ {r['term_end']}"
            for r in rows
        )

    # ── 格式化 ────────────────────────────────────────────
    @staticmethod
    def _fmt_event(e: dict[str, Any]) -> str:
        span = e["start_date"].isoformat()
        if e["end_date"] != e["start_date"]:
            span += f" ~ {e['end_date'].isoformat()}"

        parts = [f"[{e['event_type']}] {span} {e['name']}"]
        if e["affects_weekday"]:
            parts.append(f"补周{_WEEKDAY_CN[e['affects_weekday'] - 1]}的课")
        if e["is_tentative"]:
            parts.append("【暂定，可能调整】")
        if e["note"]:
            parts.append(f"备注：{e['note']}")
        return "；".join(parts)


if __name__ == "__main__":
    tool = AcademicCalendarTool()
    print(tool.run(**{"query_type": "day_info", "date": "2026-12-30"}))
    print()
    print(tool.run(**{"query_type": "list_events", "academic_year": "2026-2027", "term": "fall"}))