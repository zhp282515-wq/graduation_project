"""Background collection of structured, content-free operational facts."""
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Full, Queue
from threading import Thread
from time import perf_counter
from uuid import uuid4

from session.operations_signals import keywords, similar, topic

log = logging.getLogger(__name__)
current_run = ContextVar("operations_run", default=None)
BUSINESS_TOOLS = {"knowledge_search", "academic_calendar", "get_weather", "websearch"}
AUDIT_ACTIONS = {
    "upload_knowledge_document": "提交知识库入库",
    "delete_knowledge_document": "删除知识库文档",
    "update_visibility": "修改文档可见范围",
    "sync_knowledge": "同步知识库",
    "update_model_settings": "更新模型配置",
    "mark_gap": "处理知识缺口",
}
SECURITY_KINDS = {"sensitive_block", "suspected_injection", "crisis"}
QUESTION = """INSERT INTO operations_questions
    (id,occurred_at,user_id,role,session_id,topic,keywords,repeated)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING"""
ANSWER = """INSERT INTO operations_answers
    (id,occurred_at,role,user_id,message_id,revision,route,success,error,first_ms,elapsed_ms,
    searches,hits,empty_searches,cited,used_web,documents)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING"""
TOOL = """INSERT INTO operations_tools
    (id,occurred_at,role,user_id,name,error,elapsed_ms,keyword,results)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING"""
EVENT = "INSERT INTO operations_events(kind,object_id,actor_id) VALUES (%s,%s,%s)"
SECURITY_EVENT = """WITH enabled AS (
    INSERT INTO operations_coverage(metric) VALUES (%s) ON CONFLICT DO NOTHING
    ) INSERT INTO operations_events(kind) VALUES (%s)"""


def setup(conn):
    conn.execute(Path(__file__).with_name("operations_schema.sql").read_text(encoding="utf-8"))


def register_activity(conn, occurred, user_id, role):
    conn.execute("""INSERT INTO operations_active_days VALUES
        ((%s::timestamptz AT TIME ZONE 'Asia/Shanghai')::date,%s,%s) ON CONFLICT DO NOTHING""",
        (occurred, user_id, role))
    conn.execute("""INSERT INTO operations_first_activity VALUES (%s,%s,%s)
        ON CONFLICT (user_id) DO UPDATE SET occurred_at=excluded.occurred_at,role=excluded.role
        WHERE excluded.occurred_at < operations_first_activity.occurred_at""", (user_id, occurred, role))
    conn.execute("""INSERT INTO operations_rollup_pending
        VALUES ((%s::timestamptz AT TIME ZONE 'Asia/Shanghai')::date) ON CONFLICT DO NOTHING""", (occurred,))


class OperationsWriter:
    def __init__(self, pool):
        self.pool = pool
        self.queue = Queue(maxsize=4096)
        self.worker = Thread(target=self.consume, name="operations-writer", daemon=True)
        self.worker.start()

    def submit(self, sql, params):
        try:
            self.queue.put_nowait((sql, params))
        except Full:
            log.error("运营统计写入队列已满")

    def consume(self):
        while (item := self.queue.get()) is not None:
            sql, params = item
            try:
                with self.pool.connection(timeout=5) as conn, conn.transaction():
                    conn.execute(sql, params)
                    if sql == QUESTION:
                        register_activity(conn, *params[1:4])
            except Exception:
                log.error("运营统计写入失败")

    def close(self):
        self.queue.put(None)
        self.worker.join()


class AnswerRun:
    def __init__(self, writer, actor):
        self.writer = writer
        self.user_id, self.role = actor["id"], actor["role"]
        self.id = uuid4().hex
        self.timestamp = datetime.now(timezone.utc)
        self.started = perf_counter()
        self.first_ms = None
        self.tools = []
        self.finished = False

    @contextmanager
    def bind(self):
        token = current_run.set(self)
        try:
            yield
        finally:
            current_run.reset(token)

    def question(self, session_id, message, history):
        if not message.created_at:
            return
        text = message.content[:4000]
        previous = next((m for m in reversed(history)
                         if m.role == "user" and m.content and m.created_at), None)
        repeated = (bool(previous and message.created_at - previous.created_at <= timedelta(minutes=10)
                         and similar(text, previous.content)) if text.strip() else None)
        first = next((m.content[:4000] for m in history if m.role == "user" and m.content), text)
        self.writer.submit(QUESTION, (message.id, message.created_at, self.user_id, self.role, session_id,
                                     topic(first), keywords(text), repeated))

    def tool(self, name, error, started, query=None, results=None):
        if name not in BUSINESS_TOOLS:
            return
        ended = perf_counter()
        self.tools.append((ended, name, error, results))
        normalized = (" ".join(keywords(query[:4000])) or None) if isinstance(query, str) else None
        self.writer.submit(TOOL, (uuid4().hex, datetime.now(timezone.utc), self.role, self.user_id,
                                 name, error, int((ended - started) * 1000), normalized, results))

    def event(self, event):
        kind = event.get("type")
        if kind == "text_delta" and event.get("content") and self.first_ms is None:
            self.first_ms = int((perf_counter() - self.started) * 1000)
        elif kind == "run_failed":
            category = {
                "TimeoutError": "timeout", "ReadTimeout": "timeout",
                "ConnectTimeout": "timeout", "HTTPStatusError": "upstream",
            }.get(event.get("error_type"), "answer_failed")
            self.finish(error=category)
        elif kind == "done":
            final = event["final_answer"]
            sources = final.get("sources") or []
            documents = sorted({
                s["file_md5"] for s in sources if re.fullmatch("[0-9a-f]{32}", s.get("file_md5") or "")
            })
            self.finish(final=final, cited=bool(sources), documents=documents)

    def finish(self, *, final=None, error=None, cited=False, documents=()):
        if self.finished:
            return
        self.finished = True
        ordered = sorted(self.tools, key=lambda call: call[0])
        successful = [call for call in ordered if not call[2]]
        route = (successful or ordered)[-1][1] if ordered else "direct"
        retrievals = [call for call in ordered if call[1] in {"knowledge_search", "websearch"}]
        knowledge = [call for call in retrievals if not call[2] and call[1] == "knowledge_search"]
        self.writer.submit(ANSWER, (
            self.id, self.timestamp, self.role, self.user_id,
            final.get("message_id") if final else None, final.get("revision", 0) if final else None,
            route, final is not None, error, self.first_ms,
            int((perf_counter() - self.started) * 1000), len(retrievals),
            sum(bool(call[3]) for call in retrievals if not call[2]),
            sum(call[3] == 0 for call in knowledge), cited,
            any(call[1] == "websearch" for call in retrievals), list(documents),
        ))


def observe_tool(name, error, started, query=None, results=None):
    if run := current_run.get():
        try:
            run.tool(name, error, started, query, results)
        except Exception:
            log.error("工具运营埋点失败")


def security_event(writer, kind):
    """Integration point for detectors. No account, query or other payload is accepted."""
    if writer and kind in SECURITY_KINDS:
        writer.submit(SECURITY_EVENT, (kind, kind))
