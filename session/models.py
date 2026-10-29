from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

SessionStatus = Literal["active", "archived"]

DEFAULT_SESSION_TITLE = "新会话"


@dataclass
class Session:
    id: str
    user_id: str
    title: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    context_revision: int = 0


@dataclass
class Message:
    id: int
    session_id: str
    role: str
    content: str
    created_at: datetime | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    token_usage: dict[str, Any] | None = None
    images: list[str] | None = None
    sources: list[dict[str, Any]] | None = None
    reply_to_message_id: int | None = None


@dataclass
class Memory:
    id: str
    user_id: str
    content: str
    category: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Note:
    """用户从回答里一键存下的 Markdown 笔记。内容原样保存，不做二次渲染。"""

    id: str
    user_id: str
    title: str
    content: str
    source_session_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
