from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from session.models import Message, Session

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL DEFAULT '',
    tool_calls   JSONB,
    tool_call_id TEXT,
    token_usage  JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id);
"""


def _to_session(row: dict[str, Any]) -> Session:
    return Session(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_message(row: dict[str, Any]) -> Message:
    return Message(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
        tool_calls=row["tool_calls"],
        tool_call_id=row["tool_call_id"],
        token_usage=row["token_usage"],
    )


class PostgresSessionRepository:
    """基于 psycopg 的同步实现。连接由外部注入，生命周期不归它管。"""

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def setup(self) -> None:
        """建表，幂等，可重复调用。"""
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)
        self._conn.commit()

    def create_session(self, title: str) -> Session:
        session_id = uuid4().hex
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO sessions (id, title)
                VALUES (%s, %s)
                RETURNING id, title, status, created_at, updated_at
                """,
                (session_id, title),
            )
            row = cur.fetchone()
        self._conn.commit()
        return _to_session(row)

    def get_session(self, session_id: str) -> Session | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, title, status, created_at, updated_at FROM sessions WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()
        return _to_session(row) if row else None

    def list_sessions(self) -> list[Session]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, title, status, created_at, updated_at
                FROM sessions
                ORDER BY updated_at DESC
                """
            )
            rows = cur.fetchall()
        return [_to_session(row) for row in rows]

    def update_session_title(self, session_id: str, title: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET title = %s, updated_at = now() WHERE id = %s",
                (title, session_id),
            )
        self._conn.commit()

    def touch_session(self, session_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET updated_at = now() WHERE id = %s",
                (session_id,),
            )
        self._conn.commit()

    def delete_session(self, session_id: str) -> bool:
        """删除会话行；messages 由外键 ON DELETE CASCADE 一并删除。"""
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
            deleted = cur.rowcount > 0
        self._conn.commit()
        return deleted

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> Message:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, token_usage)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, session_id, role, content, created_at, tool_calls, tool_call_id, token_usage
                """,
                (
                    session_id,
                    role,
                    content,
                    Jsonb(tool_calls) if tool_calls is not None else None,
                    tool_call_id,
                    Jsonb(token_usage) if token_usage is not None else None,
                ),
            )
            row = cur.fetchone()
        self._conn.commit()
        return _to_message(row)

    def get_messages(self, session_id: str) -> list[Message]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, session_id, role, content, created_at, tool_calls, tool_call_id, token_usage
                FROM messages
                WHERE session_id = %s
                ORDER BY id ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        return [_to_message(row) for row in rows]