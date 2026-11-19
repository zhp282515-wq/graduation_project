"""Per-provider call accounting. Only numeric receipts enter the background writer."""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from uuid import uuid4

from session import log_context

log = logging.getLogger(__name__)
_actor = ContextVar("usage_actor", default=None)
_receipt = ContextVar("usage_receipt", default=None)
# Offline lexical tokenizer: CJK characters, short Latin subwords, punctuation.
_PIECES = re.compile(r"[\u3400-\u9fff]|[a-zA-Z0-9]{1,4}|[^\s]", re.UNICODE)


def setup(conn):
    conn.execute(Path(__file__).with_name("usage_schema.sql").read_text(encoding="utf-8"))


ACTIVITY_INSERT = """INSERT INTO usage_activity_events(event_id,occurred_at,role,tool_name)
                     VALUES (%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING"""


def record_question(conn, row):
    actor = _actor.get()
    if actor is not None:
        try:
            with conn.transaction():
                conn.execute(ACTIVITY_INSERT, (f"message:{row['id']}", row["created_at"], actor.role, None))
        except Exception:
            log.exception("消息次数写入失败")


def record_tool(name):
    actor = _actor.get()
    if actor is not None:
        try:
            actor.writer.submit_tool((uuid4().hex, datetime.now(timezone.utc), actor.role, name))
        except Exception:
            log.exception("工具次数采集失败")


def insert_event(conn, values):
    """The primary key makes replay and daily increments idempotent in one statement."""
    result = conn.execute("""
        WITH inserted AS (
          INSERT INTO token_usage_calls
            (event_id,user_id,role,session_id,model,input_tokens,output_tokens,total_tokens,source,estimated,created_at)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *
        ), aggregated AS (
        INSERT INTO token_usage_confirmed_daily(day,user_id,role,input_tokens,output_tokens,total_tokens,calls)
        SELECT (created_at AT TIME ZONE 'Asia/Shanghai')::date,user_id,role,coalesce(input_tokens,0),coalesce(output_tokens,0),total_tokens,1
        FROM inserted WHERE NOT estimated ON CONFLICT (day,user_id,role) DO UPDATE SET
          input_tokens=token_usage_confirmed_daily.input_tokens+excluded.input_tokens,
          output_tokens=token_usage_confirmed_daily.output_tokens+excluded.output_tokens,
          total_tokens=token_usage_confirmed_daily.total_tokens+excluded.total_tokens,
          calls=token_usage_confirmed_daily.calls+1
        )
        SELECT count(*)::int AS n FROM inserted
    """, values).fetchone()
    return result["n"] if isinstance(result, dict) else result[0]


class UsageWriter:
    def __init__(self, pool):
        self.pool = pool
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="usage")

    def submit(self, values):
        self.worker.submit(self._write, values)

    def submit_tool(self, values):
        self.worker.submit(self._write_tool, values)

    def _write_tool(self, values):
        try:
            with self.pool.connection() as conn:
                conn.execute(ACTIVITY_INSERT, values)
        except Exception:
            log.exception("工具次数写入失败")

    def _write(self, values):
        try:
            with self.pool.connection() as conn:
                insert_event(conn, values)
        except Exception:
            with log_context.bind(log_context.user_id, values[1]):
                log.exception("Token 用量写入失败")

    def close(self):
        self.worker.shutdown(wait=True)


@dataclass(frozen=True)
class Attribution:
    writer: UsageWriter
    user_id: str
    role: str
    session_id: str | None

    def run(self, function, *args, **kwargs):
        token = _actor.set(self if self.writer else None)
        try:
            with log_context.bind(log_context.user_id, self.user_id):
                return function(*args, **kwargs)
        finally:
            _actor.reset(token)


def observed(usage):
    """Keep only the last provider usage, including billable error responses."""
    receipt = _receipt.get()
    if receipt is not None and isinstance(usage, dict) and usage:
        receipt.update(usage=usage)


def error_usage(body):
    try:
        data = json.loads(body)
        return data.get("usage") if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def estimate(value):
    if not value:
        return 0
    if isinstance(value, str):
        if value.startswith("data:image/"):
            return 256
        return sum(1 for _ in _PIECES.finditer(value))
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return sum(estimate(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(estimate(v) for v in value)
    return estimate(str(value))


def counts(usage, inputs, outputs, input_only=False):
    def number(*keys):
        for key in keys:
            value = (usage or {}).get(key)
            if type(value) is int and value >= 0:
                return value
        return None

    incoming = number("input_tokens", "prompt_tokens")
    outgoing = number("output_tokens", "completion_tokens")
    if outgoing is None and input_only:
        outgoing = 0
    total = number("total_tokens")
    if total is None and incoming is not None and outgoing is not None:
        total = incoming + outgoing
    if total is not None:
        if (incoming or 0) + (outgoing or 0) > total:
            # Inconsistent breakdown. Only the provider's total is usable.
            incoming = outgoing = None
        elif incoming is None and outgoing is not None:
            incoming = total - outgoing
        elif outgoing is None and incoming is not None:
            outgoing = total - incoming
        return incoming, outgoing, total, False
    incoming = incoming if incoming is not None else estimate(inputs)
    outgoing = outgoing if outgoing is not None else estimate(outputs)
    return incoming, outgoing, incoming + outgoing, True


def record(model, usage, inputs, outputs, source, *, input_only=False):
    actor = _actor.get()
    if actor is None:
        return
    try:
        incoming, outgoing, total, estimated = counts(usage, inputs, outputs, input_only)
        if total:
            actor.writer.submit((uuid4().hex, actor.user_id, actor.role, actor.session_id, model,
                                 incoming, outgoing, total, source, estimated, datetime.now(timezone.utc)))
    except Exception:
        log.exception("Token 用量采集失败")


def auxiliary(model, usage, inputs):
    actor = _actor.get()
    record(model, usage, inputs, None, "tool_loop" if actor and actor.session_id else "other", input_only=True)


def call_source(messages, tools):
    if not tools:
        return "other"
    return "tool_loop" if messages and messages[-1].role == "tool" else "chat"


def metered_stream(method):
    @wraps(method)
    def wrapper(self, messages, tools=None, *args, **kwargs):
        stream = log_context.model_stream(method(self, messages, tools, *args, **kwargs), self.model)
        actor = _actor.get()
        if actor is None:
            yield from stream
            return
        receipt, parts = {}, []
        completed = False
        try:
            while True:
                token = _receipt.set(receipt)
                try:
                    event = next(stream, None)
                finally:
                    _receipt.reset(token)
                if event is None:
                    break
                kind = event.get("type")
                if kind == "done":
                    completed = True
                    if event.get("token_usage"):
                        receipt["usage"] = event["token_usage"]
                elif kind in ("reasoning_delta", "text_delta", "tool_call"):
                    parts.append(event.get("content") or event.get("tool_call"))
                yield event
        finally:
            try:
                stream.close()
            finally:
                if completed or any(parts) or receipt:
                    actor.run(record, self.model, receipt.get("usage"), [messages, tools], parts,
                              call_source(messages, tools))
    return wrapper


def metered_invoke(method):
    method = log_context.model_method()(method)
    @wraps(method)
    def wrapper(self, messages, tools=None, *args, **kwargs):
        if _actor.get() is None:
            return method(self, messages, tools, *args, **kwargs)
        receipt = {}
        token = _receipt.set(receipt)
        response = None
        try:
            response = method(self, messages, tools, *args, **kwargs)
            return response
        finally:
            _receipt.reset(token)
            if response is not None or receipt:
                outputs = [response.content, response.reasoning, response.tool_calls] if response else []
                record(self.model, receipt.get("usage") or getattr(response, "token_usage", None),
                       [messages, tools], outputs, call_source(messages, tools))
    return wrapper
