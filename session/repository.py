from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from session.models import Memory, Message, Session

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
    images       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    content     TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'fact',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memories_user ON memories (user_id, updated_at DESC);
"""

# 迁移单独放：必须在建索引之前跑，且不能带 NOT NULL DEFAULT
# ——那样旧行会被静默填成空串，后面回填时就分不清“空值”和“新加的”了。
_MIGRATE = """
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS images JSONB;
"""


def _to_session(row: dict[str, Any]) -> Session:
    return Session(
        id=row["id"],
        user_id=row["user_id"],
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
        images=row["images"],
    )


def _to_memory(row: dict[str, Any]) -> Memory:
    return Memory(
        id=row["id"],
        user_id=row["user_id"],
        content=row["content"],
        category=row["category"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresSessionRepository:
    """基于 psycopg 的同步实现。连接由外部注入，生命周期不归它管。"""

    def __init__(self, conn: psycopg.Connection, *, legacy_user_id: str = ""):
        self._conn = conn
        self._legacy_user_id = legacy_user_id

    def setup(self) -> None:
        """建表 + 迁移 + 建索引，幂等，可重复调用。

        顺序不能变：索引引用 user_id，必须先补列再建索引。
        """
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)
            cur.execute(_MIGRATE)
            cur.execute(
                "UPDATE sessions SET user_id = %s WHERE user_id IS NULL OR user_id = ''",
                (self._legacy_user_id,),
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, updated_at DESC)"
            )
        self._conn.commit()

    def create_session(self, user_id: str, title: str) -> Session:
        session_id = uuid4().hex
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO sessions (id, user_id, title)
                VALUES (%s, %s, %s)
                RETURNING id, user_id, title, status, created_at, updated_at
                """,
                (session_id, user_id, title),
            )
            row = cur.fetchone()
        self._conn.commit()
        return _to_session(row)

    def find_empty_session(self, user_id: str, default_title: str) -> Session | None:
        """找出该用户最早的一个空会话（标题仍是默认标题且没有任何消息）。

        用 NOT EXISTS 而不是 LEFT JOIN + GROUP BY，避免消息多时聚合整表。
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, user_id, title, status, created_at, updated_at
                FROM sessions s
                WHERE s.user_id = %s
                  AND s.title = %s
                  AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
                ORDER BY s.created_at ASC
                LIMIT 1
                """,
                (user_id, default_title),
            )
            row = cur.fetchone()
        return _to_session(row) if row else None

    def get_session(self, user_id: str, session_id: str) -> Session | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, user_id, title, status, created_at, updated_at
                FROM sessions
                WHERE id = %s AND user_id = %s
                """,
                (session_id, user_id),
            )
            row = cur.fetchone()
        return _to_session(row) if row else None

    def list_sessions(self, user_id: str) -> list[Session]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, user_id, title, status, created_at, updated_at
                FROM sessions
                WHERE user_id = %s
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        return [_to_session(row) for row in rows]

    def update_session_title(self, user_id: str, session_id: str, title: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sessions SET title = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (title, session_id, user_id),
            )
        self._conn.commit()

    def touch_session(self, session_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET updated_at = now() WHERE id = %s",
                (session_id,),
            )
        self._conn.commit()

    def delete_session(self, user_id: str, session_id: str) -> bool:
        """删除会话行；messages 由外键 ON DELETE CASCADE 一并删除。"""
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sessions WHERE id = %s AND user_id = %s",
                (session_id, user_id),
            )
            deleted = cur.rowcount > 0
        self._conn.commit()
        return deleted

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        images: list[str] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> Message:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, token_usage, images)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, session_id, role, content, created_at, tool_calls, tool_call_id, token_usage, images
                """,
                (
                    session_id,
                    role,
                    content,
                    Jsonb(tool_calls) if tool_calls is not None else None,
                    tool_call_id,
                    Jsonb(token_usage) if token_usage is not None else None,
                    Jsonb(images) if images is not None else None,
                ),
            )
            row = cur.fetchone()
        self._conn.commit()
        return _to_message(row)

    def complete_turn(
        self, session_id: str, content: str, *, token_usage: dict[str, Any] | None = None,
    ) -> None:
        """助手回答与会话时间一起提交；适用于 autocommit 连接。"""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO messages (session_id, role, content, token_usage) VALUES (%s, 'assistant', %s, %s)",
                    (session_id, content, Jsonb(token_usage) if token_usage is not None else None),
                )
                cur.execute("UPDATE sessions SET updated_at = now() WHERE id = %s", (session_id,))
                if cur.rowcount != 1:
                    raise ValueError("会话已不存在，无法保存回答")
        # 兼容脚本传入的非 autocommit 连接（读取历史可能已开启外层事务）。
        self._conn.commit()

    def get_messages(self, user_id: str, session_id: str) -> list[Message]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT m.id, m.session_id, m.role, m.content, m.created_at,
                       m.tool_calls, m.tool_call_id, m.token_usage, m.images
                FROM messages m
                JOIN sessions s ON s.id = m.session_id
                WHERE m.session_id = %s AND s.user_id = %s
                ORDER BY m.id ASC
                """,
                (session_id, user_id),
            )
            rows = cur.fetchall()
        return [_to_message(row) for row in rows]

    # ---------- 长期记忆 ----------
    def add_memory(self, user_id: str, content: str, category: str = "fact") -> Memory:
        memory_id = uuid4().hex
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO memories (id, user_id, content, category)
                VALUES (%s, %s, %s, %s)
                RETURNING id, user_id, content, category, created_at, updated_at
                """,
                (memory_id, user_id, content, category),
            )
            row = cur.fetchone()
        self._conn.commit()
        return _to_memory(row)

    def list_memories(self, user_id: str) -> list[Memory]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, user_id, content, category, created_at, updated_at
                FROM memories
                WHERE user_id = %s
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        return [_to_memory(row) for row in rows]

    def update_memory(self, user_id: str, memory_id: str, content: str) -> Memory | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE memories SET content = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, content, category, created_at, updated_at
                """,
                (content, memory_id, user_id),
            )
            row = cur.fetchone()
        self._conn.commit()
        return _to_memory(row) if row else None

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM memories WHERE id = %s AND user_id = %s",
                (memory_id, user_id),
            )
            deleted = cur.rowcount > 0
        self._conn.commit()
        return deleted
